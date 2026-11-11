"""
Voxlyne - CRM Providers

Available providers:
- GenericWebhookProvider: Send data to any HTTP endpoint
- HubSpotProvider: Create contacts and deals in HubSpot
"""

from app.services.crm.providers.hubspot import HubSpotProvider
from app.services.crm.providers.webhook import GenericWebhookProvider

__all__ = [
    "GenericWebhookProvider",
    "HubSpotProvider",
]
