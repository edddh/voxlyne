"""Reserved identity for the isolated, read-only showcase tenant."""

from uuid import UUID

DEMO_TENANT_ID = UUID("cd913b69-5afd-4ef0-86a0-5ad009c34cb4")
DEMO_TENANT_SLUG = "demo-showcase"


def is_demo_tenant(tenant_id) -> bool:
    return tenant_id is not None and str(tenant_id) == str(DEMO_TENANT_ID)
