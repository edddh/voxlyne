"""
Ascolta - CRM Integration Module

This module provides CRM synchronization capabilities:
- Generic webhook dispatcher for any HTTP endpoint
- HubSpot integration (Contact + Deal creation)
- Flexible data mapping with JSONPath support
- Retry logic with exponential backoff
- Sync tracking and admin visibility
"""

from app.services.crm.base import CRMProvider, CRMSyncResult
from app.services.crm.dispatcher import CRMDispatcher
from app.services.crm.mapper import DataMapper

__all__ = [
    "CRMProvider",
    "CRMSyncResult",
    "CRMDispatcher",
    "DataMapper",
]
