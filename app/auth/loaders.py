from app.extensions import login_manager
from app.models import User
from sqlalchemy.orm import joinedload
import logging
from sqlalchemy.exc import SQLAlchemyError

# Configure logger
logger = logging.getLogger(__name__)


@login_manager.user_loader
def load_user(user_id):
    """
    Loads the user object for Flask-Login using the user_id.
    This function is required by Flask-Login to manage user sessions.

    Args:
        user_id (int): The ID of the user to load.

    Returns:
        User: The user object if found, or None if not found or if an error occurred.
    """
    try:
        # Ensure user_id is a valid integer before querying
        user_id = int(user_id)

        # Load the user with eager-loaded relationships to prevent detached session issues
        user = User.query.options(
            joinedload(User.uploaded_files),  # Preload uploaded files if frequently accessed
            joinedload(User.spreadsheets)  # Preload spreadsheets if frequently accessed
        ).get(user_id)

        if not user:
            logger.warning(f"User with ID {user_id} not found.")
            return None

        logger.info(f"User with ID {user_id} successfully loaded.")
        return user

    except ValueError:
        logger.error("Invalid user_id provided (not an integer).")
        return None
    except SQLAlchemyError as e:
        logger.error(f"SQLAlchemy error while loading user with ID {user_id}: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error in load_user: {e}", exc_info=True)
        return None
