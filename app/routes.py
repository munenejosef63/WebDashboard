import os
import logging
from flask import Blueprint, render_template, request, flash, current_app, jsonify, redirect, url_for
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import joinedload
from datetime import datetime
from flask_wtf.csrf import CSRFProtect
from app.models import Spreadsheet, Sheet, Link, db, get_quick_stats
from .utils import allowed_file, process_uploaded_file

# Initialize logger
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Create a blueprint for the main routes
main_bp = Blueprint('main', __name__)


UPLOAD_PROGRESS = {}  # Optional global state to track upload progress (if needed)

@main_bp.route('/')
def index():
    """
    Redirect the user to the appropriate page based on authentication status.
    """
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))
    return redirect(url_for('auth.login'))

@main_bp.route('/dashboard', methods=['GET'])
@login_required
def dashboard():
    """
    Render the user dashboard with spreadsheets, sections, and statistics.
    """
    try:
        user_spreadsheets = (
            db.session.query(Spreadsheet)
            .options(joinedload(Spreadsheet.sheets))
            .filter_by(user_id=current_user.id)
            .all()
        )

        # Calculate sections excluding credentials sheets
        sections = [
            sheet
            for spreadsheet in user_spreadsheets
            for sheet in spreadsheet.sheets
            if sheet.name.lower() != 'credentials'
        ]

        # Get quick stats
        stats = get_quick_stats(current_user.id)

        return render_template(
            'dashboard.html',
            spreadsheets=user_spreadsheets,
            sections=sections,
            total_files=stats['total_files'],
            total_sections=stats['total_sections'],
            last_upload=stats['last_upload']
        )

    except SQLAlchemyError as e:
        logger.error(f"Database error loading dashboard: {str(e)}")
        flash("Failed to load dashboard data from database", "danger")
        return redirect(url_for('auth.login'))

    except Exception as e:
        logger.error(f"Unexpected dashboard error: {str(e)}", exc_info=True)
        flash("An unexpected error occurred while loading the dashboard", "danger")
        return redirect(url_for('auth.login'))


@main_bp.route('/upload', methods=['POST'])
@login_required
def upload_file():
    """Handles file upload with enhanced error diagnostics and transaction management."""
    file_path = None
    try:
        # ==== File Reception Validation ====
        if 'file' not in request.files:
            logger.error("Upload error: No file part in request")
            return jsonify({
                "status": "error",
                "message": "No file selected for upload.",
                "error_code": "NO_FILE_PART"
            }), 400

        file = request.files['file']

        # ==== Empty File Check ====
        if not file or file.filename == '':
            logger.error("Upload error: Empty file submission")
            return jsonify({
                "status": "error",
                "message": "Empty file submission.",
                "error_code": "EMPTY_FILE"
            }), 400

        # ==== File Size Validation ====
        try:
            file.seek(0, os.SEEK_END)
            file_length = file.tell()
            file.seek(0)
            logger.info(f"File upload initiated: {file.filename} ({file_length} bytes)")

            if file_length > current_app.config['MAX_CONTENT_LENGTH']:
                logger.error(f"File size exceeded: {file_length} bytes")
                return jsonify({
                    "status": "error",
                    "message": "File size exceeds maximum allowed limit.",
                    "max_size": f"{current_app.config['MAX_CONTENT_LENGTH'] // (1024 * 1024)}MB",
                    "error_code": "FILE_TOO_LARGE"
                }), 413
        except OSError as e:
            logger.error(f"File size check failed: {str(e)}")
            return jsonify({
                "status": "error",
                "message": "Invalid file content.",
                "error_code": "INVALID_FILE_CONTENT"
            }), 400

        # ==== File Type Validation ====
        if not allowed_file(file.filename):
            logger.error(f"Invalid file type: {file.filename}")
            return jsonify({
                "status": "error",
                "message": "Invalid file format.",
                "allowed_formats": current_app.config['ALLOWED_EXTENSIONS'],
                "error_code": "INVALID_FILE_TYPE"
            }), 400

        # ==== Secure File Storage ====
        upload_folder = current_app.config['UPLOAD_FOLDER']
        os.makedirs(upload_folder, exist_ok=True)
        filename = secure_filename(file.filename)
        file_path = os.path.join(upload_folder, filename)

        try:
            file.save(file_path)
            logger.debug(f"Temporary file stored: {file_path}")
            if not os.path.exists(file_path):
                raise RuntimeError("File save verification failed")
        except Exception as e:
            logger.error(f"File save failed: {str(e)}")
            return jsonify({
                "status": "error",
                "message": "Failed to store temporary file.",
                "error_code": "FILE_STORAGE_FAILURE"
            }), 500

        # ==== Database Health Check ====
        try:
            db.session.execute(text("SELECT 1"))
            logger.debug("Database connection verified")
        except SQLAlchemyError as e:
            logger.critical(f"Database connection failed: {str(e)}")
            return jsonify({
                "status": "error",
                "message": "Database unavailable.",
                "error_code": "DB_CONNECTION_FAILURE"
            }), 503

        # ==== Transaction Management ====
        try:
            logger.info("Initiating database transaction")
            db.session.begin_nested()

            # ==== Existing Data Cleanup ====
            logger.debug(f"Checking for existing spreadsheets: {filename}")
            deleted_count = Spreadsheet.query.filter_by(
                user_id=current_user.id,
                name=filename
            ).delete(synchronize_session=False)
            logger.info(f"Removed {deleted_count} existing spreadsheet entries")

            # ==== File Processing ====
            logger.info("Starting file processing pipeline")
            status = process_uploaded_file(file_path, current_user.id)
            db.session.commit()
            logger.info(f"Transaction committed successfully: {status}")

            return jsonify({
                "status": "success",
                "message": "File processed successfully" if status == "uploaded"
                else "File updated successfully",
                "filename": filename,
                "redirect": url_for('main.dashboard'),
                "stats": get_quick_stats(current_user.id)
            }), 200

        except ValueError as ve:
            db.session.rollback()
            logger.warning(f"Validation failed: {str(ve)}")
            return jsonify({
                "status": "error",
                "message": "File validation failed",
                "details": str(ve).split('\n'),
                "template_url": url_for('static', filename='template.xlsx'),
                "error_code": "VALIDATION_FAILURE"
            }), 400

        except SQLAlchemyError as sae:
            db.session.rollback()
            logger.error(f"Database error: {str(sae)}", exc_info=True)
            return jsonify({
                "status": "error",
                "message": "Data storage failure.",
                "error_code": "DB_SAVE_FAILURE",
                "database_error": str(sae.orig) if sae.orig else str(sae)
            }), 500

        except Exception as e:
            db.session.rollback()
            logger.error(f"Unexpected processing error: {str(e)}", exc_info=True)
            raise

    except Exception as e:
        logger.critical(f"Critical upload failure: {str(e)}", exc_info=True)
        return jsonify({
            "status": "error",
            "message": "System error. Contact support if problem persists.",
            "error_code": "SYSTEM_FAILURE",
            "reference_id": str(uuid.uuid4())  # For support tracking
        }), 500

    finally:
        # ==== Resource Cleanup ====
        if file_path and os.path.exists(file_path):
            try:
                os.remove(file_path)
                logger.debug(f"Temporary file cleaned: {file_path}")
            except Exception as cleanup_error:
                logger.error(
                    f"File cleanup failed for {file_path}: {str(cleanup_error)}",
                    exc_info=True
                )

@main_bp.route('/upload/progress', methods=['GET'])
@login_required
def upload_progress():
    """
    Provides detailed upload progress information including:
    - Overall progress percentage
    - Current processing stage
    - Active sheet being processed
    """
    try:
        progress_data = UPLOAD_PROGRESS.get(current_user.id, {
            "progress": 0,
            "status": "Not started",
            "current_sheet": "",
            "timestamp": datetime.utcnow().isoformat()
        })

        # Ensure minimum data structure format
        response_data = {
            "progress": progress_data.get("progress", 0),
            "status": f"{progress_data.get('status', '')}".strip(),
            "current_sheet": progress_data.get("current_sheet", ""),
            "last_update": progress_data.get("timestamp", datetime.utcnow().isoformat())
        }

        # Clean up combined status if sheet name is empty
        if not response_data["current_sheet"]:
            response_data["status"] = response_data["status"].split("-")[0].strip()

        return jsonify(response_data), 200

    except Exception as e:
        logger.error(f"Progress check failed: {str(e)}", exc_info=True)
        return jsonify({
            "progress": 0,
            "status": "Error retrieving progress",
            "current_sheet": "",
            "error": str(e)
        }), 500


# Change existing section_details route to dashboard_section
@main_bp.route('/dashboard/<section_name>')
@login_required
def dashboard_section(section_name):
    """Show dashboard for a specific section with proper user isolation."""
    try:
        # Get current section with user validation
        current_section = Sheet.query \
            .join(Spreadsheet) \
            .filter(
            Sheet.name == section_name,
            Spreadsheet.user_id == current_user.id
        ) \
            .options(joinedload(Sheet.links)) \
            .first_or_404()

        # Get all user sections for navigation
        user_spreadsheets = Spreadsheet.query \
            .options(joinedload(Spreadsheet.sheets)) \
            .filter_by(user_id=current_user.id) \
            .all()

        sections = [
            sheet
            for spreadsheet in user_spreadsheets
            for sheet in spreadsheet.sheets
            if sheet.name.lower() != 'credentials'
        ]

        # Prepare links data
        data = [{
            'title': link.title,
            'url': link.link,
            'status': (link.status or 'unknown').lower()
        } for link in current_section.links]

        return render_template(
            'section_dashboard.html',
            current_section=current_section,
            sections=sections,
            data=data,
            # Pass stats for header display
            total_files=len(user_spreadsheets),
            total_sections=len(sections),
            last_upload=max(
                [s.created_at for s in user_spreadsheets],
                default=datetime.utcnow()
            )
        )

    except SQLAlchemyError as e:
        logger.error(f"Database error in section dashboard: {str(e)}")
        flash("Failed to load section data", "danger")
        return redirect(url_for('main.dashboard'))

    except Exception as e:
        logger.error(f"Unexpected section dashboard error: {str(e)}")
        flash("An unexpected error occurred", "danger")
        return redirect(url_for('main.dashboard'))

@main_bp.route('/add_link', methods=['POST'])
@login_required
def add_link():
    try:
        data = request.get_json()
        new_link = Link(
            sheet_id=data['section_id'],
            title=data['title'],
            link=data['url'],
            status=data['status']
        )
        db.session.add(new_link)
        db.session.commit()

        return jsonify({
            "status": "success",
            "link": {
                "title": new_link.title,
                "url": new_link.link,
                "status": new_link.status
            }
        }), 200

    except Exception as e:
        logger.error(f"Link creation error: {str(e)}")
        db.session.rollback()
        return jsonify({"status": "error", "message": str(e)}), 500

@main_bp.route('/get-sections')
@login_required
def get_sections():
    """Return dynamically updated sections list HTML"""
    try:
        user_spreadsheets = Spreadsheet.query.options(
            joinedload(Spreadsheet.sheets)
        ).filter_by(user_id=current_user.id).all()

        sections = []
        for spreadsheet in user_spreadsheets:
            sheets = [sheet for sheet in spreadsheet.sheets if sheet.name.lower() != 'credentials']
            sections.extend(sheets)

        return render_template('_sections.html', sections=sections)

    except SQLAlchemyError as e:
        logger.error(f"Database error fetching sections: {e}")
        return "Error loading sections", 500
    except Exception as e:
        logger.error(f"Unexpected error fetching sections: {e}")
        return "Error loading sections", 500


# routes.py
@main_bp.route('/get-stats')
@login_required
def get_stats():
    """Return current statistics as JSON"""
    try:
        # Explicitly refresh session state
        db.session.expire_all()
        stats = get_quick_stats(current_user.id)
        return jsonify({
            'total_files': stats['total_files'],
            'total_sections': stats['total_sections'],
            'last_upload': stats['last_upload'].isoformat() if stats['last_upload'] else None
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@main_bp.route('/create_section', methods=['POST'])
@login_required
def create_section():
    try:
        # Get JSON data instead of form data
        data = request.get_json()
        spreadsheet_id = data.get('spreadsheet_id')
        section_name = data.get('section_name')

        # Validate input
        if not all([spreadsheet_id, section_name]):
            return jsonify({
                "status": "error",
                "message": "Both spreadsheet ID and section name are required"
            }), 400

        # Verify spreadsheet exists and belongs to user
        spreadsheet = Spreadsheet.query.filter_by(
            id=spreadsheet_id,
            user_id=current_user.id
        ).first()

        if not spreadsheet:
            return jsonify({
                "status": "error",
                "message": "Spreadsheet not found or access denied"
            }), 404

        # Create new section
        new_sheet = Sheet(
            name=section_name,
            spreadsheet_id=spreadsheet.id
        )
        db.session.add(new_sheet)
        db.session.commit()

        return jsonify({
            "status": "success",
            "message": "Section created successfully",
            "section": {
                "id": new_sheet.id,
                "name": new_sheet.name,
                "spreadsheet_id": new_sheet.spreadsheet_id
            }
        }), 200

    except SQLAlchemyError as e:
        logger.error(f"Database error creating section: {str(e)}")
        db.session.rollback()
        return jsonify({
            "status": "error",
            "message": "Database operation failed"
        }), 500

    except Exception as e:
        logger.error(f"Unexpected error creating section: {str(e)}")
        return jsonify({
            "status": "error",
            "message": "Internal server error"
        }), 500

@main_bp.route('/get_status_options')
@login_required
def get_status_options():
    try:
        statuses = (
            db.session.query(Link.status)
            .join(Sheet)
            .join(Spreadsheet)
            .filter(Spreadsheet.user_id == current_user.id)
            .distinct()
            .all()
        )
        return jsonify([status[0] for status in statuses if status[0]])
    except Exception as e:
        current_app.logger.error(f"Status options error: {str(e)}", exc_info=True)
        return jsonify({"error": "Failed to load status options"}), 500
