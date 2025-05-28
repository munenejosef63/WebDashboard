from flask import Blueprint, jsonify
from flask_login import current_user, login_required
from app.models import Spreadsheet, Sheet, Link
import logging

# Initialize Blueprint and logger
api_bp = Blueprint('api', __name__)
logger = logging.getLogger(__name__)


@api_bp.route('/api/dashboard-data', methods=['GET'])
@login_required
def dashboard_data():
    """
    API endpoint that provides data for the dashboard if the user has uploaded spreadsheets.
    """
    try:
        # Ensure the user has uploaded at least one spreadsheet
        user_spreadsheets = Spreadsheet.query.filter_by(user_id=current_user.id).all()
        if not user_spreadsheets:
            return jsonify({
                "status": "error",
                "message": "No spreadsheets available. Please upload a file to access data."
            }), 403

        # Prepare dashboard data
        dashboard_items = []
        for spreadsheet in user_spreadsheets:
            spreadsheet_data = {
                "spreadsheet_name": spreadsheet.name,
                "created_at": spreadsheet.created_at.strftime('%Y-%m-%d %H:%M:%S'),
                "sheets": []
            }

            for sheet in spreadsheet.sheets:
                sheet_data = {
                    "sheet_name": sheet.name,
                    "links": [
                        {
                            "id": link.id,
                            "title": link.title,
                            "url": link.link,
                            "status": link.status
                        }
                        for link in sheet.links
                    ]
                }
                spreadsheet_data["sheets"].append(sheet_data)

            dashboard_items.append(spreadsheet_data)

        return jsonify({
            "status": "success",
            "dashboard_data": dashboard_items
        })

    except Exception as e:
        logger.error(f"Error in /api/dashboard-data: {e}", exc_info=True)
        return jsonify({
            "status": "error",
            "message": "An error occurred while fetching dashboard data."
        }), 500
