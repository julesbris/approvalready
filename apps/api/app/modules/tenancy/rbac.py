"""Role and permission catalogue.

This is the source the 0002 migration seeded from (0004 added ``source.manage`` and
``rule.author``); ``tests/test_audit_rbac.py`` asserts the database still matches it.
Authorisation decisions read the database, so changing a mapping means a new migration,
never just an edit here.
"""

from __future__ import annotations

from enum import StrEnum

from app.modules.tenancy.models import OrganisationKind as K


class RoleKey(StrEnum):
    CUSTOMER = "CUSTOMER"
    ORG_ADMIN = "ORG_ADMIN"
    PROFESSIONAL = "PROFESSIONAL"
    PARTNER_USER = "PARTNER_USER"
    PARTNER_ADMIN = "PARTNER_ADMIN"
    STAFF = "STAFF"
    ADMIN = "ADMIN"
    SUPERADMIN = "SUPERADMIN"


class Perm(StrEnum):
    ORG_READ = "org.read"
    ORG_UPDATE = "org.update"
    ORG_MEMBERS_READ = "org.members.read"
    ORG_MEMBERS_MANAGE = "org.members.manage"
    ORG_INVITATIONS_MANAGE = "org.invitations.manage"
    ORG_AUDIT_READ = "org.audit.read"
    PROJECT_READ = "project.read"
    PROJECT_WRITE = "project.write"
    REVIEW_PERFORM = "review.perform"
    LEAD_READ = "lead.read"
    LEAD_CLAIM = "lead.claim"
    SOURCE_MANAGE = "source.manage"
    SOURCE_VERIFY = "source.verify"
    RULE_AUTHOR = "rule.author"
    RULE_PUBLISH = "rule.publish"
    PLATFORM_USERS_READ = "platform.users.read"
    PLATFORM_ORGANISATIONS_READ = "platform.organisations.read"
    PLATFORM_AUDIT_READ = "platform.audit.read"
    PLATFORM_ROLES_MANAGE = "platform.roles.manage"


PERMISSION_DESCRIPTIONS: dict[Perm, str] = {
    Perm.ORG_READ: "View the organisation",
    Perm.ORG_UPDATE: "Edit organisation details",
    Perm.ORG_MEMBERS_READ: "View organisation members",
    Perm.ORG_MEMBERS_MANAGE: "Change member roles and remove members",
    Perm.ORG_INVITATIONS_MANAGE: "Invite people to the organisation",
    Perm.ORG_AUDIT_READ: "View the organisation's audit log",
    Perm.PROJECT_READ: "View projects",
    Perm.PROJECT_WRITE: "Create and edit projects",
    Perm.REVIEW_PERFORM: "Perform professional reviews",
    Perm.LEAD_READ: "View anonymised leads",
    Perm.LEAD_CLAIM: "Claim leads",
    Perm.SOURCE_MANAGE: "Capture and edit regulatory sources",
    Perm.SOURCE_VERIFY: "Verify regulatory source references",
    Perm.RULE_AUTHOR: "Draft and test rules",
    Perm.RULE_PUBLISH: "Publish rule versions",
    Perm.PLATFORM_USERS_READ: "View any user (staff)",
    Perm.PLATFORM_ORGANISATIONS_READ: "View any organisation (staff)",
    Perm.PLATFORM_AUDIT_READ: "View and verify the platform audit log",
    Perm.PLATFORM_ROLES_MANAGE: "Grant platform roles",
}

_ORG_ADMIN = {
    Perm.ORG_READ,
    Perm.ORG_UPDATE,
    Perm.ORG_MEMBERS_READ,
    Perm.ORG_MEMBERS_MANAGE,
    Perm.ORG_INVITATIONS_MANAGE,
    Perm.ORG_AUDIT_READ,
}
_PARTNER_USER = {Perm.ORG_READ, Perm.ORG_MEMBERS_READ, Perm.LEAD_READ, Perm.LEAD_CLAIM}
_STAFF = {
    Perm.ORG_READ,
    Perm.ORG_MEMBERS_READ,
    Perm.PLATFORM_USERS_READ,
    Perm.PLATFORM_ORGANISATIONS_READ,
    Perm.SOURCE_MANAGE,
    Perm.SOURCE_VERIFY,
    Perm.RULE_AUTHOR,
}
_ADMIN = _STAFF | _ORG_ADMIN | {Perm.PLATFORM_AUDIT_READ, Perm.RULE_PUBLISH}


ROLES: dict[RoleKey, tuple[str, str, tuple[K, ...], frozenset[Perm]]] = {
    # key: (scope, description, organisation kinds it may be granted in, permissions)
    RoleKey.CUSTOMER: (
        "ORG",
        "Customer using ApprovalReady products",
        (K.PERSONAL, K.BUSINESS),
        frozenset({Perm.ORG_READ, Perm.ORG_MEMBERS_READ, Perm.PROJECT_READ, Perm.PROJECT_WRITE}),
    ),
    RoleKey.ORG_ADMIN: (
        "ORG",
        "Manages an organisation's details and members",
        (K.PERSONAL, K.BUSINESS, K.PROFESSIONAL_PRACTICE),
        frozenset(_ORG_ADMIN),
    ),
    RoleKey.PROFESSIONAL: (
        "ORG",
        "Professional reviewer in a practice",
        (K.PROFESSIONAL_PRACTICE,),
        frozenset({Perm.ORG_READ, Perm.ORG_MEMBERS_READ, Perm.REVIEW_PERFORM, Perm.PROJECT_READ}),
    ),
    RoleKey.PARTNER_USER: (
        "ORG",
        "Partner staff member",
        (K.PARTNER,),
        frozenset(_PARTNER_USER),
    ),
    RoleKey.PARTNER_ADMIN: (
        "ORG",
        "Partner account administrator",
        (K.PARTNER,),
        frozenset(_PARTNER_USER | _ORG_ADMIN),
    ),
    RoleKey.STAFF: (
        "PLATFORM",
        "ApprovalReady staff",
        (K.PLATFORM_ADMIN,),
        frozenset(_STAFF),
    ),
    RoleKey.ADMIN: (
        "PLATFORM",
        "ApprovalReady administrator",
        (K.PLATFORM_ADMIN,),
        frozenset(_ADMIN),
    ),
    RoleKey.SUPERADMIN: (
        "PLATFORM",
        "ApprovalReady super administrator",
        (K.PLATFORM_ADMIN,),
        frozenset(_ADMIN | {Perm.PLATFORM_ROLES_MANAGE}),
    ),
}

# Roles given to the creator of a new organisation, by kind.
CREATOR_ROLES: dict[K, tuple[RoleKey, ...]] = {
    K.PERSONAL: (RoleKey.CUSTOMER, RoleKey.ORG_ADMIN),
    K.BUSINESS: (RoleKey.CUSTOMER, RoleKey.ORG_ADMIN),
    K.PROFESSIONAL_PRACTICE: (RoleKey.PROFESSIONAL, RoleKey.ORG_ADMIN),
    K.PARTNER: (RoleKey.PARTNER_ADMIN,),
    K.PLATFORM_ADMIN: (RoleKey.SUPERADMIN,),
}

# Kinds a user can create through the API. Partner organisations arrive through the partner
# application and verification flow (Milestone 14); the platform organisation via the CLI.
SELF_SERVICE_KINDS = (K.BUSINESS, K.PROFESSIONAL_PRACTICE)

# Kinds that may have more than one member. A personal account is one person.
MULTI_MEMBER_KINDS = (K.BUSINESS, K.PROFESSIONAL_PRACTICE, K.PARTNER, K.PLATFORM_ADMIN)
