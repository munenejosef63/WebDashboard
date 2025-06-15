import os
import logging
import uuid
from flask import Blueprint, render_template, request, flash, current_app, jsonify, redirect, url_for
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import joinedload
from datetime import datetime
from flask_wtf.csrf import validate_csrf, CSRFError
from app.models import Spreadsheet, Sheet, Link, db, get_quick_stats
from .utils import allowed_file, process_uploaded_file
from .utils import UPLOAD_PROGRESS
from flask import send_from_directory
from sqlalchemy import or_

# Configure detailed logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('app_debug.log')
    ]
)
logger = logging.getLogger(__name__)

# Create blueprint
main_bp = Blueprint('main', __name__)

@main_bp.route('/')
def index():
    """Redirect based on authentication status"""
    logger.debug(f"Index route accessed. User authenticated: {current_user.is_authenticated}")
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))
    return redirect(url_for('auth.login'))


@main_bp.route('/dashboard', methods=['GET'])
@login_required
def dashboard():
    """Dashboard with enhanced logging and database verification"""
    try:
        logger.info(f"Loading dashboard for user: {current_user.id}")

        # Query user spreadsheets with relationships
        user_spreadsheets = (
            db.session.query(Spreadsheet)
            .options(joinedload(Spreadsheet.sheets))
            .filter_by(user_id=current_user.id)
            .all()
        )
        logger.debug(f"Found {len(user_spreadsheets)} spreadsheets for user")

        # Process sections excluding credentials
        sections = [
            sheet
            for spreadsheet in user_spreadsheets
            for sheet in spreadsheet.sheets
            # if sheet.name.lower() != 'credentials'
        ]
        logger.debug(f"Identified {len(sections)} valid sections")

        # Get and verify stats
        stats = get_quick_stats(current_user.id)
        logger.info(
            f"Dashboard stats - Files: {stats['total_files']}, Sections: {stats['total_sections']}, Last Upload: {stats['last_upload']}")

        # Verify data consistency
        if stats['total_files'] != len(user_spreadsheets):
            logger.warning(f"Stat file count mismatch: {stats['total_files']} vs {len(user_spreadsheets)}")

        return render_template(
            'dashboard.html',
            spreadsheets=user_spreadsheets,
            sections=sections,
            total_files=stats['total_files'],
            total_sections=stats['total_sections'],
            last_upload=stats['last_upload']
        )

    except SQLAlchemyError as e:
        logger.critical(f"DATABASE ERROR: {str(e)}", exc_info=True)
        flash("Failed to load dashboard data from database", "danger")
        return redirect(url_for('auth.login'))
    except Exception as e:
        logger.critical(f"UNEXPECTED ERROR: {str(e)}", exc_info=True)
        flash("System error loading dashboard", "danger")
        return redirect(url_for('auth.login'))


@main_bp.route('/upload', methods=['POST'])
@login_required
def upload_file():
    """File upload handler with detailed transaction logging"""
    file_path = None
    try:
        # Validate CSRF token
        validate_csrf(request.form.get('csrf_token'))
        logger.debug("CSRF token validated successfully")

        # File existence check
        if 'file' not in request.files:
            logger.error("Upload request missing 'file' part")
            return jsonify({
                "status": "error",
                "message": "No file selected",
                "error_code": "NO_FILE_PART"
            }), 400

        file = request.files['file']

        # Empty file check
        if not file or file.filename == '':
            logger.error("Empty file submission detected")
            return jsonify({
                "status": "error",
                "message": "Empty file submission",
                "error_code": "EMPTY_FILE"
            }), 400

        # File size validation
        try:
            file.seek(0, os.SEEK_END)
            file_length = file.tell()
            file.seek(0)
            logger.debug(f"File '{file.filename}' size: {file_length} bytes")

            if file_length > current_app.config['MAX_CONTENT_LENGTH']:
                logger.error(f"File size {file_length} exceeds limit {current_app.config['MAX_CONTENT_LENGTH']}")
                return jsonify({
                    "status": "error",
                    "message": "File size exceeds limit",
                    "error_code": "FILE_TOO_LARGE"
                }), 413
        except OSError as e:
            logger.error(f"File size check failed: {str(e)}")
            return jsonify({
                "status": "error",
                "message": "Invalid file content",
                "error_code": "INVALID_FILE_CONTENT"
            }), 400

        # File type validation
        if not allowed_file(file.filename):
            logger.error(f"Invalid file type: {file.filename}")
            return jsonify({
                "status": "error",
                "message": "Invalid file format",
                "error_code": "INVALID_FILE_TYPE"
            }), 400

        # Secure file storage
        upload_folder = current_app.config['UPLOAD_FOLDER']
        os.makedirs(upload_folder, exist_ok=True)
        filename = secure_filename(file.filename)
        file_path = os.path.join(upload_folder, filename)
        logger.debug(f"Saving file to temporary location: {file_path}")

        try:
            file.save(file_path)
            if not os.path.exists(file_path):
                logger.critical("File save verification failed - file not found")
                raise RuntimeError("File save verification failed")
            logger.info("File saved successfully to temporary storage")
        except Exception as e:
            logger.error(f"File save failed: {str(e)}")
            return jsonify({
                "status": "error",
                "message": "Failed to store file",
                "error_code": "FILE_STORAGE_FAILURE"
            }), 500

        # Database health check
        try:
            db.session.execute(text("SELECT 1"))
            logger.debug("Database connection verified")
        except SQLAlchemyError as e:
            logger.critical(f"Database health check failed: {str(e)}")
            return jsonify({
                "status": "error",
                "message": "Database unavailable",
                "error_code": "DB_CONNECTION_FAILURE"
            }), 503

        # Transaction management
        try:
            logger.info("Starting database transaction")
            db.session.begin_nested()

            # Remove existing entries
            deleted_count = Spreadsheet.query.filter_by(
                user_id=current_user.id,
                name=filename
            ).delete(synchronize_session=False)
            logger.info(f"Deleted {deleted_count} existing spreadsheet entries")

            # Process file
            logger.debug(f"Processing file: {file_path}")
            status = process_uploaded_file(file_path, current_user.id)
            logger.info(f"File processing completed with status: {status}")

            # Commit transaction
            db.session.commit()
            logger.info("Database transaction committed successfully")
            db.session.expire_all()

            # Verify database update
            new_spreadsheet = Spreadsheet.query.filter_by(
                user_id=current_user.id,
                name=filename
            ).first()

            if not new_spreadsheet:
                logger.critical("DATABASE UPDATE VERIFICATION FAILED: Spreadsheet not found after upload")
                raise RuntimeError("Spreadsheet creation verification failed")

            logger.info(f"Spreadsheet created successfully. ID: {new_spreadsheet.id}")

            return jsonify({
                "status": "success",
                "message": "File processed successfully",
                "filename": filename,
                "redirect": url_for('main.dashboard'),
                "stats": get_quick_stats(current_user.id)
            }), 200

        except ValueError as ve:
            db.session.rollback()
            logger.error(f"Validation error: {str(ve)}")
            return jsonify({
                "status": "error",
                "message": "File validation failed",
                "details": str(ve),
                "error_code": "VALIDATION_FAILURE"
            }), 400

        except SQLAlchemyError as sae:
            db.session.rollback()
            logger.critical(f"Database error: {str(sae)}", exc_info=True)
            return jsonify({
                "status": "error",
                "message": "Database operation failed",
                "error_code": "DB_SAVE_FAILURE"
            }), 500

        except Exception as e:
            db.session.rollback()
            logger.critical(f"Processing error: {str(e)}", exc_info=True)
            raise

    except Exception as e:
        logger.critical(f"UPLOAD PROCESS FAILURE: {str(e)}", exc_info=True)
        return jsonify({
            "status": "error",
            "message": "System error during upload",
            "error_code": "SYSTEM_FAILURE",
            "reference_id": str(uuid.uuid4())
        }), 500

    finally:
        # Cleanup temporary file
        if file_path and os.path.exists(file_path):
            try:
                os.remove(file_path)
                logger.debug(f"Temporary file removed: {file_path}")
            except Exception as e:
                logger.error(f"Cleanup error: {str(e)}")


@main_bp.route('/upload/progress', methods=['GET'])
@login_required
def upload_progress():
    """Upload progress tracker with detailed logging"""
    try:
        logger.debug(f"Upload progress requested for user: {current_user.id}")
        progress_data = UPLOAD_PROGRESS.get(current_user.id, {
            "progress": 0,
            "status": "Not started",
            "current_sheet": "",
            "timestamp": datetime.utcnow().isoformat()
        })
        logger.debug(f"Returning progress data: {progress_data}")
        return jsonify(progress_data), 200
    except Exception as e:
        logger.error(f"Progress check failed: {str(e)}", exc_info=True)
        return jsonify({
            "progress": 0,
            "status": "Error retrieving progress",
            "error": str(e)
        }), 500


@main_bp.route('/dashboard/<section_name>')
@login_required
def dashboard_section(section_name):
    """Section dashboard with access control and verification"""
    try:
        logger.info(f"Loading section: {section_name} for user: {current_user.id}")

        # Get current section with user validation
        current_section = Sheet.query \
            .join(Spreadsheet) \
            .filter(
            Sheet.name == section_name,
            Spreadsheet.user_id == current_user.id
        ) \
            .options(joinedload(Sheet.links)) \
            .first()

        if not current_section:
            logger.warning(f"Section not found: {section_name}")
            return render_template('404.html'), 404

        logger.debug(f"Section found: ID {current_section.id}")

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
        logger.debug(f"Found {len(sections)} sections for navigation")

        # Prepare links data
        links = current_section.links
        logger.info(f"Section contains {len(links)} links")
        data = [{
            'id': link.id,
            'title': link.title,
            'url': link.link,
            'status': link.status or 'unknown'
        } for link in links]

        # Calculate stats
        last_upload = max(
            [s.created_at for s in user_spreadsheets],
            default=datetime.utcnow()
        )
        logger.debug(f"Last upload: {last_upload}")

        return render_template(
            'section_dashboard.html',
            current_section=current_section,
            sections=sections,
            data=data,
            total_files=len(user_spreadsheets),
            total_sections=len(sections),
            last_upload=last_upload
        )

    except SQLAlchemyError as e:
        logger.error(f"Database error loading section: {str(e)}", exc_info=True)
        flash("Database error loading section", "danger")
        return redirect(url_for('main.dashboard'))
    except Exception as e:
        logger.error(f"Unexpected error in section dashboard: {str(e)}", exc_info=True)
        flash("System error loading section", "danger")
        return redirect(url_for('main.dashboard'))


@main_bp.route('/add_link', methods=['POST'])
@login_required
def add_link():
    """Link creation with transaction verification"""
    try:
        data = request.get_json()
        logger.debug(f"Add link request data: {data}")

        # Validate input
        if not all(key in data for key in ['section_id', 'title', 'url', 'status']):
            logger.error("Missing required fields in link creation")
            return jsonify({
                "status": "error",
                "message": "Missing required fields"
            }), 400

        # Create and save link
        new_link = Link(
            sheet_id=data['section_id'],
            title=data['title'],
            link=data['url'],
            status=data['status']
        )
        db.session.add(new_link)
        db.session.commit()
        logger.info(f"Link created successfully. ID: {new_link.id}")

        # Verify database entry
        db_link = Link.query.get(new_link.id)
        if not db_link:
            logger.critical("LINK CREATION VERIFICATION FAILED: Record not found")
            raise RuntimeError("Link creation verification failed")

        logger.debug(f"Link verified in database: ID {db_link.id}")

        return jsonify({
            "status": "success",
            "link": {
                "title": db_link.title,
                "url": db_link.link,
                "status": db_link.status
            }
        }), 200

    except SQLAlchemyError as e:
        logger.error(f"Database error creating link: {str(e)}", exc_info=True)
        db.session.rollback()
        return jsonify({
            "status": "error",
            "message": "Database operation failed"
        }), 500
    except Exception as e:
        logger.error(f"Unexpected error creating link: {str(e)}", exc_info=True)
        db.session.rollback()
        return jsonify({
            "status": "error",
            "message": "System error creating link"
        }), 500


@main_bp.route('/get-sections')
@login_required
def get_sections():
    """Dynamic sections loader with error handling"""
    try:
        logger.debug("Loading sections for dynamic update")

        user_spreadsheets = Spreadsheet.query.options(
            joinedload(Spreadsheet.sheets)
        ).filter_by(user_id=current_user.id).all()

        sections = []
        for spreadsheet in user_spreadsheets:
            sheets = [sheet for sheet in spreadsheet.sheets if sheet.name.lower() != 'credentials']
            sections.extend(sheets)

        logger.info(f"Returning {len(sections)} sections for rendering")
        return render_template('_sections.html', sections=sections)

    except SQLAlchemyError as e:
        logger.error(f"Database error loading sections: {str(e)}", exc_info=True)
        return "Error loading sections", 500
    except Exception as e:
        logger.error(f"Unexpected error loading sections: {str(e)}", exc_info=True)
        return "Error loading sections", 500


@main_bp.route('/get-stats')
@login_required
def get_stats():
    """Statistics endpoint with verification"""
    try:
        logger.debug("Refreshing quick stats")
        db.session.expire_all()  # Refresh ORM state
        stats = get_quick_stats(current_user.id)

        # Verify stats integrity
        if not all(key in stats for key in ['total_files', 'total_sections', 'last_upload']):
            logger.error("Incomplete stats data returned")
            raise ValueError("Incomplete statistics data")

        logger.info(f"Returning stats: {stats}")
        return jsonify({
            'total_files': stats['total_files'],
            'total_sections': stats['total_sections'],
            'last_upload': stats['last_upload'].isoformat() if stats['last_upload'] else None
        })
    except Exception as e:
        logger.error(f"Error loading stats: {str(e)}", exc_info=True)
        return jsonify({"error": "Failed to load statistics"}), 500


@main_bp.route('/create_section', methods=['POST'])
@login_required
def create_section():
    try:
        # Get and validate data
        section_name = request.form.get('name')
        spreadsheet_id = request.form.get('spreadsheet_id')

        if not section_name or not spreadsheet_id:
            return jsonify({
                "success": False,
                "error": "Missing required fields"
            }), 400

        try:
            spreadsheet_id = int(spreadsheet_id)
        except ValueError:
            return jsonify({
                "success": False,
                "error": "Invalid spreadsheet ID format"
            }), 400

        # Verify spreadsheet ownership
        spreadsheet = Spreadsheet.query.filter_by(
            id=spreadsheet_id,
            user_id=current_user.id
        ).first()

        if not spreadsheet:
            return jsonify({
                "success": False,
                "error": "Spreadsheet not found or access denied"
            }), 404

        # Check for duplicate section name
        if Sheet.query.filter_by(name=section_name, spreadsheet_id=spreadsheet.id).first():
            return jsonify({
                "success": False,
                "error": "Section name already exists in this spreadsheet"
            }), 400

        # Create and save section
        new_sheet = Sheet(
            name=section_name,
            spreadsheet_id=spreadsheet.id
        )
        db.session.add(new_sheet)
        db.session.commit()

        return jsonify({
            "success": True,
            "message": "Section created successfully",
            "section": {
                "id": new_sheet.id,
                "name": new_sheet.name
            }
        }), 200

    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.error(f"Database error: {str(e)}")
        return jsonify({
            "success": False,
            "error": "Database operation failed"
        }), 500
    except Exception as e:
        current_app.logger.error(f"Unexpected error: {str(e)}")
        return jsonify({
            "success": False,
            "error": "Internal server error"
        }), 500


@main_bp.route('/get_status_options')
@login_required
def get_status_options():
    """Status options loader with error handling"""
    try:
        logger.debug("Loading distinct status options")
        statuses = (
            db.session.query(Link.status)
            .join(Sheet)
            .join(Spreadsheet)
            .filter(Spreadsheet.user_id == current_user.id)
            .distinct()
            .all()
        )
        options = [status[0] for status in statuses if status[0]]
        logger.info(f"Found {len(options)} distinct status options")
        return jsonify(options)
    except Exception as e:
        logger.error(f"Error loading status options: {str(e)}", exc_info=True)
        return jsonify({"error": "Failed to load status options"}), 500

@main_bp.route('/delete_link/<int:link_id>', methods=['DELETE'])
@login_required
def delete_link(link_id):
    """Delete a link with ownership verification"""
    try:
        # Verify link exists and belongs to current user
        link = Link.query \
            .join(Sheet) \
            .join(Spreadsheet) \
            .filter(
                Link.id == link_id,
                Spreadsheet.user_id == current_user.id
            ).first()

        if not link:
            logger.warning(f"Link not found or access denied: {link_id}")
            return jsonify({
                "status": "error",
                "message": "Link not found or access denied"
            }), 404

        # Delete link
        db.session.delete(link)
        db.session.commit()
        logger.info(f"Link deleted: ID {link_id}")

        return jsonify({
            "status": "success",
            "message": "Link deleted successfully"
        }), 200

    except SQLAlchemyError as e:
        logger.error(f"Database error deleting link: {str(e)}", exc_info=True)
        db.session.rollback()
        return jsonify({
            "status": "error",
            "message": "Database operation failed"
        }), 500
    except Exception as e:
        logger.error(f"Unexpected error deleting link: {str(e)}", exc_info=True)
        return jsonify({
            "status": "error",
            "message": "System error deleting link"
        }), 500


@main_bp.route('/delete_section', methods=['POST'])
@login_required
def delete_section():
    try:
        # Get JSON data from request
        data = request.get_json()
        section_id = data.get('section_id')

        if not section_id:
            return jsonify({"success": False, "error": "Missing section ID"}), 400

        try:
            section_id = int(section_id)
        except ValueError:
            return jsonify({"success": False, "error": "Invalid section ID"}), 400

        # Verify section ownership
        section = Sheet.query \
            .join(Spreadsheet) \
            .filter(
            Sheet.id == section_id,
            Spreadsheet.user_id == current_user.id
        ).first()

        if not section:
            return jsonify({"success": False, "error": "Section not found or access denied"}), 404

        # Delete all links in the section
        Link.query.filter_by(sheet_id=section.id).delete()

        # Delete the section
        db.session.delete(section)
        db.session.commit()

        return jsonify({
            "success": True,
            "message": "Section and all its records deleted successfully"
        }), 200

    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.error(f"Database error deleting section: {str(e)}")
        return jsonify({
            "success": False,
            "error": "Database operation failed"
        }), 500
    except Exception as e:
        current_app.logger.error(f"Unexpected error deleting section: {str(e)}")
        return jsonify({
            "success": False,
            "error": "Internal server error"
        }), 500


@main_bp.route('/rename_section', methods=['POST'])
@login_required
def rename_section():
    try:
        # Get JSON data from request
        data = request.get_json()
        section_id = data.get('section_id')
        new_name = data.get('new_name')

        if not section_id or not new_name:
            return jsonify({"success": False, "error": "Missing required fields"}), 400

        try:
            section_id = int(section_id)
        except ValueError:
            return jsonify({"success": False, "error": "Invalid section ID"}), 400

        # Verify section ownership
        section = Sheet.query \
            .join(Spreadsheet) \
            .filter(
            Sheet.id == section_id,
            Spreadsheet.user_id == current_user.id
        ).first()

        if not section:
            return jsonify({"success": False, "error": "Section not found or access denied"}), 404

        # Check if new name already exists in the same spreadsheet
        existing_section = Sheet.query.filter(
            Sheet.name == new_name,
            Sheet.spreadsheet_id == section.spreadsheet_id,
            Sheet.id != section.id
        ).first()

        if existing_section:
            return jsonify({
                "success": False,
                "error": "Section name already exists in this spreadsheet"
            }), 400

        # Update the section name
        section.name = new_name
        db.session.commit()

        return jsonify({
            "success": True,
            "message": "Section renamed successfully",
            "section": {
                "id": section.id,
                "name": section.name
            }
        }), 200

    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.error(f"Database error renaming section: {str(e)}")
        return jsonify({
            "success": False,
            "error": "Database operation failed"
        }), 500
    except Exception as e:
        current_app.logger.error(f"Unexpected error renaming section: {str(e)}")
        return jsonify({
            "success": False,
            "error": "Internal server error"
        }), 500


@main_bp.route('/download-template')
def download_template():
    return send_from_directory(
        'static/files',
        'template.xlsx',
        as_attachment=True,
        download_name='WebLinks_Upload_Template.xlsx'
    )


@main_bp.route('/search_links', methods=['GET'])
@login_required
def search_links():
    """Search links by title or URL with ownership verification"""
    try:
        query = request.args.get('query', '').strip()
        section_id = request.args.get('section_id', type=int)

        logger.info(f"Searching links for user: {current_user.id} | Query: '{query}' | Section: {section_id}")

        # Validate input
        if not query or not section_id:
            logger.debug("Missing query or section_id")
            return jsonify([]), 200

        # Verify section belongs to user
        section = Sheet.query \
            .join(Spreadsheet) \
            .filter(
            Sheet.id == section_id,
            Spreadsheet.user_id == current_user.id
        ).first()

        if not section:
            logger.warning(f"Section not found or access denied: {section_id}")
            return jsonify({
                "status": "error",
                "message": "Section not found or access denied"
            }), 404

        # Search in both title and URL fields
        results = Link.query.filter(
            Link.sheet_id == section_id,
            or_(
                Link.title.ilike(f'%{query}%'),
                Link.link.ilike(f'%{query}%')
            )
        ).all()

        # Format results for JSON response
        links = [{
            'id': link.id,
            'title': link.title,
            'url': link.link,
            'status': link.status or 'unknown'
        } for link in results]

        logger.info(f"Found {len(links)} matching links")
        return jsonify(links)

    except SQLAlchemyError as e:
        logger.error(f"Database search error: {str(e)}", exc_info=True)
        return jsonify({
            "status": "error",
            "message": "Database operation failed"
        }), 500
    except Exception as e:
        logger.error(f"Search error: {str(e)}", exc_info=True)
        return jsonify({
            "status": "error",
            "message": "System error during search"
        }), 500


@main_bp.route('/update_link', methods=['POST'])
@login_required
def update_link():
    """Update a link with ownership verification"""
    try:
        data = request.get_json()
        link_id = data.get('id')
        title = data.get('title')
        url = data.get('url')
        status = data.get('status')

        logger.info(f"Updating link: {link_id} | User: {current_user.id}")
        logger.debug(f"Update data: {data}")

        # Validate input
        if not link_id or not title or not url or not status:
            logger.error("Missing required fields in update request")
            return jsonify({
                "status": "error",
                "message": "Missing required fields"
            }), 400

        # Find the link to update and verify ownership
        link = Link.query \
            .join(Sheet) \
            .join(Spreadsheet) \
            .filter(
            Link.id == link_id,
            Spreadsheet.user_id == current_user.id
        ).first()

        if not link:
            logger.warning(f"Link not found or access denied: {link_id}")
            return jsonify({
                "status": "error",
                "message": "Link not found or access denied"
            }), 404

        # Update the link
        link.title = title
        link.link = url
        link.status = status

        # Commit changes to database
        db.session.commit()
        logger.info(f"Link updated successfully: ID {link_id}")

        return jsonify({
            "status": "success",
            "message": "Link updated successfully",
            "link": {
                "id": link.id,
                "title": link.title,
                "url": link.link,
                "status": link.status
            }
        })

    except SQLAlchemyError as e:
        db.session.rollback()
        logger.error(f"Database update error: {str(e)}", exc_info=True)
        return jsonify({
            "status": "error",
            "message": "Database operation failed"
        }), 500
    except Exception as e:
        db.session.rollback()
        logger.error(f"Update error: {str(e)}", exc_info=True)
        return jsonify({
            "status": "error",
            "message": "System error during update"
        }), 500