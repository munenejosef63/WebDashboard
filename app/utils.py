import os
import pandas as pd
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from app.models import Spreadsheet, Sheet, Link, db
import logging
from datetime import datetime
from typing import Dict, List


def normalize_column_name(col: str) -> str:
    """Normalize column names: strip whitespace, lower, replace spaces and underscores."""
    return col.strip().lower().replace(' ', '_').replace('-', '_')

# Initialize logger
logger = logging.getLogger(__name__)

# Global progress tracker for uploads
UPLOAD_PROGRESS: Dict[int, Dict] = {}

# Allowed file extensions and required columns
ALLOWED_EXTENSIONS = {'csv', 'xls', 'xlsx'}
REQUIRED_COLUMNS = {'title', 'link', 'status'}


def allowed_file(filename: str) -> bool:
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def process_uploaded_file(file_path: str, user_id: int) -> str:
    """Process uploaded file with comprehensive validation and error handling"""
    global UPLOAD_PROGRESS
    uploaded_file_name = os.path.basename(file_path)
    validation_errors: List[str] = []
    status = "uploaded"

    try:
        UPLOAD_PROGRESS[user_id] = {
            "status": "Initializing",
            "progress": 0,
            "current_sheet": ""
        }

        # Read and validate file structure
        UPLOAD_PROGRESS[user_id].update({"status": "Reading file", "progress": 5})
        sheet_data, file_type = read_and_validate_file(file_path)

        UPLOAD_PROGRESS[user_id].update({"status": "Validating", "progress": 10})
        validate_sheet_structures(sheet_data, validation_errors)

        if validation_errors:
            raise ValueError("\n".join(validation_errors))

        # Process valid file
        UPLOAD_PROGRESS[user_id].update({"status": "Database setup", "progress": 20})
        existing_spreadsheet = Spreadsheet.query.filter_by(
            name=uploaded_file_name,
            user_id=user_id
        ).first()

        if existing_spreadsheet:
            status = "updated"
            logger.info(f"Replacing existing file: {uploaded_file_name}")
            cleanup_existing_spreadsheet(existing_spreadsheet)

        # Process sheets with progress tracking
        total_sheets = len([n for n in sheet_data if n.lower() != 'credentials'])
        processed_sheets = 0

        def update_progress(sheet_name: str):
            nonlocal processed_sheets
            progress = 20 + int((processed_sheets / total_sheets) * 70) if total_sheets else 0
            UPLOAD_PROGRESS[user_id].update({
                "status": f"Processing {sheet_name}",
                "progress": progress,
                "current_sheet": sheet_name
            })
            processed_sheets += 1

        result = process_valid_spreadsheet(
            uploaded_file_name,
            user_id,
            sheet_data,
            status,
            progress_callback=update_progress
        )

        UPLOAD_PROGRESS[user_id].update({"status": "Finalizing", "progress": 95})
        db.session.commit()

        return result

    except ValueError as ve:
        db.session.rollback()
        logger.warning(f"Validation errors:\n{str(ve)}")
        raise
    except IntegrityError as e:
        db.session.rollback()
        logger.error(f"Database integrity error: {str(e)}")
        raise
    except Exception as e:
        db.session.rollback()
        logger.error(f"Unexpected error: {str(e)}", exc_info=True)
        raise
    finally:
        UPLOAD_PROGRESS.pop(user_id, None)


def read_and_validate_file(file_path: str) -> tuple:
    """Read file and return data with file type"""
    if file_path.lower().endswith(('.xls', '.xlsx')):
        return pd.read_excel(file_path, sheet_name=None), 'excel'
    if file_path.lower().endswith('.csv'):
        return {"Default": pd.read_csv(file_path)}, 'csv'
    raise ValueError("Unsupported file format")


def validate_sheet_structures(sheet_data: Dict[str, pd.DataFrame], errors: List[str]):
    """Validate all sheets meet structural requirements"""
    for sheet_name, sheet_df in sheet_data.items():
        if sheet_name.lower() == 'credentials':
            continue

        sheet_df.columns = [normalize_column_name(col) for col in sheet_df.columns]
        missing = REQUIRED_COLUMNS - set(sheet_df.columns)

        if missing:
            errors.append(
                f"Sheet '{sheet_name}' missing required columns: {', '.join(missing)}"
            )


def process_valid_spreadsheet(
        filename: str,
        user_id: int,
        sheet_data: Dict[str, pd.DataFrame],
        status: str
) -> str:
    """Process validated spreadsheet data into database"""
    new_spreadsheet = Spreadsheet(
        name=filename,
        user_id=user_id,
        created_at=datetime.utcnow()
    )
    db.session.add(new_spreadsheet)
    db.session.flush()

    total_sheets = len([n for n in sheet_data if n.lower() != 'credentials'])
    processed_sheets = 0

    for sheet_name, sheet_df in sheet_data.items():
        if sheet_name.lower() == 'credentials':
            continue

        update_progress(user_id, processed_sheets, total_sheets, sheet_name)
        process_sheet(new_spreadsheet.id, sheet_name, sheet_df)
        processed_sheets += 1

    logger.info(f"File '{filename}' successfully processed as {status}")
    return status


def update_progress(user_id: int, processed: int, total: int, sheet_name: str):
    """Update global upload progress state"""
    progress = int((processed / total) * 100) if total > 0 else 0
    UPLOAD_PROGRESS[user_id] = {
        "status": f"Processing {sheet_name}",
        "progress": progress
    }


def process_sheet(spreadsheet_id: int, sheet_name: str, sheet_df: pd.DataFrame):
    try:
        if not spreadsheet_id or not isinstance(spreadsheet_id, int):
            raise ValueError(f"Invalid spreadsheet ID: {spreadsheet_id}")
        if not sheet_name or not isinstance(sheet_name, str):
            raise ValueError(f"Invalid sheet name: {sheet_name}")
        if not isinstance(sheet_df, pd.DataFrame):
            raise TypeError(f"Expected DataFrame, got {type(sheet_df)}")

        logger.info(f"Processing sheet: {sheet_name} for spreadsheet {spreadsheet_id}")
        logger.debug(f"Initial data sample:\n{sheet_df.head(2)}")

        sheet = Sheet(name=sheet_name, spreadsheet_id=spreadsheet_id)
        db.session.add(sheet)
        db.session.flush()  # Ensure sheet.id is available

        if sheet_df.empty:
            logger.warning(f"Empty sheet detected: {sheet_name}")
            return

        sheet_df = clean_sheet_data(sheet_df)
        if sheet_df.empty:
            logger.warning(f"Sheet {sheet_name} empty after cleaning")
            return

        required_columns = {'title', 'link'}
        missing_cols = required_columns - set(sheet_df.columns)
        if missing_cols:
            raise ValueError(f"Missing columns in {sheet_name}: {missing_cols}")

        logger.info(f"Inserting {len(sheet_df)} links for sheet {sheet.id}")

        links = [
            Link(
                sheet_id=sheet.id,
                title=row['title'],
                link=row['link'],
                status=row.get('status', 'unknown')
            ) for _, row in sheet_df.iterrows()
        ]
        db.session.add_all(links)
        logger.debug(f"Added {len(links)} links for sheet {sheet.id}")

    except Exception as e:
        logger.error(f"Error processing sheet {sheet_name}: {e}", exc_info=True)
        raise

def clean_sheet_data(sheet_df: pd.DataFrame) -> pd.DataFrame:
    """Clean and normalize sheet data"""
    return (
        sheet_df
        .dropna(how='all', axis=1)
        .fillna({'status': 'Unknown'})
        .dropna(subset=['title', 'link'], how='any')  # Ensure both title and link exist
        .assign(status=lambda x: x['status'].str[:50])  # Prevent varchar overflow
    )


def insert_links(sheet_id: int, sheet_df: pd.DataFrame, batch_size: int = 500):
    """Batch insert links with validation"""
    valid_columns = get_valid_link_columns()

    # Clean data before processing
    cleaned_df = (
        sheet_df
        .pipe(clean_sheet_data)
        .loc[:, lambda df: df.columns.isin(valid_columns)]
    )

    # Convert to records and add sheet_id
    rows = cleaned_df.to_dict(orient="records")
    for row in rows:
        row['sheet_id'] = sheet_id

    # Batch process with progress tracking
    for i in range(0, len(rows), batch_size):
        batch = rows[i:i + batch_size]
        try:
            execute_batch_insert(batch)
        except IntegrityError:
            # Fallback to individual inserts for better error reporting
            logger.warning("Batch insert failed, attempting individual inserts...")
            for single_row in batch:
                try:
                    execute_batch_insert([single_row])
                except IntegrityError as e:
                    logger.error(f"Failed to insert row: {single_row} - Error: {str(e)}")
                    continue


def get_valid_link_columns() -> set:
    """Get valid column names for links table"""
    inspector = inspect(db.engine)
    return {col['name'] for col in inspector.get_columns('links')}


def execute_batch_insert(rows: List[dict]):
    """Execute batch insert with conflict handling"""
    if not rows:
        return

    try:
        # Explicitly list the conflict columns
        conflict_columns = ['sheet_id', 'title', 'link']

        query = text(f"""
            INSERT INTO links ({', '.join(f'"{c}"' for c in rows[0].keys())})
            VALUES ({', '.join(f':{c}' for c in rows[0].keys())})
            ON CONFLICT ({', '.join(conflict_columns)}) DO UPDATE
            SET {', '.join(f'"{k}" = EXCLUDED."{k}"'
                           for k in rows[0].keys()
                           if k not in conflict_columns)}
        """)

        db.session.execute(query, rows)
        db.session.commit()
    except Exception as e:
        logger.error(f"Batch insert failed: {str(e)}")
        db.session.rollback()
        raise

def cleanup_existing_spreadsheet(spreadsheet: Spreadsheet):
    """Clean up existing spreadsheet and related data"""
    try:
        logger.info(f"Cleaning up spreadsheet '{spreadsheet.name}' (ID: {spreadsheet.id})...")

        # Delete related links
        Link.query.filter(Link.sheet_id.in_([s.id for s in spreadsheet.sheets])).delete()

        # Delete sheets
        Sheet.query.filter_by(spreadsheet_id=spreadsheet.id).delete()

        # Delete spreadsheet
        db.session.delete(spreadsheet)


        logger.info(f"Successfully cleaned up spreadsheet '{spreadsheet.name}'")
    except SQLAlchemyError as e:
        logger.error(f"Cleanup failed: {str(e)}")
        db.session.rollback()
        raise