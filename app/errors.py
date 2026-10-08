class CoachError(Exception):
    """Safe, public-facing service error shared by all watch integrations."""

    def __init__(self, message, code="operation_failed", status=409):
        super().__init__(message)
        self.code = code
        self.status = status
