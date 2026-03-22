"""Output module"""

from app.modules.output.models import Output
from app.modules.output.service import output_service_obj

__all__ = ["Output", "output_service_obj"]
