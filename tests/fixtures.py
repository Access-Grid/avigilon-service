"""
Real Plasec API response shapes sourced from live captures (claude-read.txt).
Used as mock return values throughout the test suite.
"""

# ---------------------------------------------------------------------------
# Identity list  (GET /identities.json)
# ---------------------------------------------------------------------------

IDENTITY_LIST_RESPONSE = {
    "data": [
        {
            "dn": "cn=0,ou=identities,dc=plasec",
            "cn": "0",
            "plasecName": "Administrator, System",
            "plasecIdstatus": "Active",
            "plasecLasttime": None,
            "primaryPhoto": "",
        },
        {
            "dn": "cn=e01c265bdfc24d70,ou=identities,dc=plasec",
            "cn": "e01c265bdfc24d70",
            "plasecName": "Cooper, Jim",
            "plasecIdstatus": "Active",
            "plasecLasttime": None,
            "primaryPhoto": "",
        },
        {
            "dn": "cn=6961cb7d2c664248,ou=identities,dc=plasec",
            "cn": "6961cb7d2c664248",
            "plasecName": "Person, Test",
            "plasecIdstatus": "Active",
            "plasecLasttime": None,
            "primaryPhoto": "",
        },
    ],
    "meta": {"recordsTotal": 3, "recordsFiltered": 3},
    "success": True,
    "message": "Identities were successfully fetched.",
    "errors": None,
    "location": None,
}

# Same list but "Person, Test" is Inactive
IDENTITY_LIST_PERSON_INACTIVE = {
    "data": [
        {
            "dn": "cn=0,ou=identities,dc=plasec",
            "cn": "0",
            "plasecName": "Administrator, System",
            "plasecIdstatus": "Active",
            "plasecLasttime": None,
            "primaryPhoto": "",
        },
        {
            "dn": "cn=e01c265bdfc24d70,ou=identities,dc=plasec",
            "cn": "e01c265bdfc24d70",
            "plasecName": "Cooper, Jim",
            "plasecIdstatus": "Active",
            "plasecLasttime": None,
            "primaryPhoto": "",
        },
    ],
    "meta": {"recordsTotal": 2, "recordsFiltered": 2},
    "success": True,
    "message": "Identities were successfully fetched.",
    "errors": None,
    "location": None,
}

# ---------------------------------------------------------------------------
# Identity detail  (GET /identities/{cn}.json)
# ---------------------------------------------------------------------------

IDENTITY_DETAIL_PERSON = {
    "data": {
        "dn": "cn=6961cb7d2c664248,ou=identities,dc=plasec",
        "cn": "6961cb7d2c664248",
        "plasecName": "Person, Test",
        "plasecLname": "Person",
        "plasecFname": "Test",
        "plasecIdstatus": "1",
        "plasecidentityEmailaddress": "test.person@example.com",
        "plasecidentityPhone": "555-1234",
        "plasecidentityWorkphone": "",
        "plasecidentityTitle": "",
        "plasecidentityDepartment": "",
    },
    "success": True,
}

IDENTITY_DETAIL_COOPER = {
    "data": {
        "dn": "cn=e01c265bdfc24d70,ou=identities,dc=plasec",
        "cn": "e01c265bdfc24d70",
        "plasecName": "Cooper, Jim",
        "plasecLname": "Cooper",
        "plasecFname": "Jim",
        "plasecIdstatus": "1",
        "plasecidentityEmailaddress": "jim.cooper@example.com",
        "plasecidentityPhone": "555-5678",
    },
    "success": True,
}

# ---------------------------------------------------------------------------
# Token list  (GET /identities/{cn}/tokens.json)
# ---------------------------------------------------------------------------

TOKEN_LIST_ACTIVE = {
    "data": [
        {
            "cn": "54a67bf3a2944214",
            "plasecInternalnumber": "1234",
            "plasecEmbossednumber": "1234",
            "plasecPIN": "5678",
            "plasecTokenstatus": "1",
            "plasecTokenType": "0",
            "plasecTokenlevel": "0",
            "plasecIssuedate": "2026-03-09T15:22:13.000Z",
            "plasecActivatedate": "2026-03-09T15:22:13.000Z",
            "plasecDeactivatedate": "2027-03-09T15:22:13.000Z",
        }
    ],
    "meta": {"recordsTotal": 1, "recordsFiltered": 1},
    "success": True,
}

TOKEN_LIST_INACTIVE = {
    "data": [
        {
            "cn": "54a67bf3a2944214",
            "plasecInternalnumber": "1234",
            "plasecEmbossednumber": "1234",
            "plasecPIN": "5678",
            "plasecTokenstatus": "2",
            "plasecTokenType": "0",
            "plasecTokenlevel": "0",
            "plasecIssuedate": "2026-03-09T15:22:13.000Z",
            "plasecActivatedate": "2026-03-09T15:22:13.000Z",
            "plasecDeactivatedate": "2027-03-09T15:22:13.000Z",
        }
    ],
    "meta": {"recordsTotal": 1, "recordsFiltered": 1},
    "success": True,
}

TOKEN_LIST_EMPTY = {
    "data": [],
    "meta": {"recordsTotal": 0, "recordsFiltered": 0},
    "success": True,
}
