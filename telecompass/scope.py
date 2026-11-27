"""Which CCHP topics feed which of the five rule types. Plain data, decided by people (D7)."""

CROSS_STATE_LICENSURE = "cross_state_licensure"
MEDICAID_MODALITY = "medicaid_modality"
CONSENT = "consent"
ONLINE_PRESCRIBING = "online_prescribing"
PRIVATE_PAYER_PARITY = "private_payer_parity"

RULE_TYPES = (
    CROSS_STATE_LICENSURE,
    MEDICAID_MODALITY,
    CONSENT,
    ONLINE_PRESCRIBING,
    PRIVATE_PAYER_PARITY,
)

RULE_TYPE_LABELS = {
    CROSS_STATE_LICENSURE: "Cross-state licensure and registration",
    MEDICAID_MODALITY: "Medicaid coverage by modality",
    CONSENT: "Consent",
    ONLINE_PRESCRIBING: "Online prescribing",
    PRIVATE_PAYER_PARITY: "Private payer parity",
}

# (CCHP category, CCHP topic) -> rule type. Anything not listed is out of scope.
TOPIC_RULE_TYPES = {
    ("Professional Requirements", "Cross State Licensing"): CROSS_STATE_LICENSURE,
    ("Professional Requirements", "Licensure Compacts"): CROSS_STATE_LICENSURE,
    ("Medicaid", "Live Video"): MEDICAID_MODALITY,
    ("Medicaid", "Store and Forward"): MEDICAID_MODALITY,
    ("Medicaid", "Remote Patient Monitoring"): MEDICAID_MODALITY,
    ("Medicaid", "Email, Phone & Fax"): MEDICAID_MODALITY,
    ("Medicaid", "Consent Requirements"): CONSENT,
    ("Professional Requirements", "Consent Requirements"): CONSENT,
    ("Professional Requirements", "Online Prescribing"): ONLINE_PRESCRIBING,
    ("Private Payer", "Parity"): PRIVATE_PAYER_PARITY,
    ("Private Payer", "Requirements"): PRIVATE_PAYER_PARITY,
}


def rule_type_for(category: str, topic: str) -> str | None:
    """The rule type an entry feeds, or None if the entry is out of scope."""
    return TOPIC_RULE_TYPES.get((category, topic))
