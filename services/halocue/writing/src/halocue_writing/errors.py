class DomainError(Exception):
    def __init__(self, code: str, message: str, *, status: int = 400, details=None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.details = details or {}


class NotFound(DomainError):
    def __init__(self, resource: str, resource_id: str):
        super().__init__(
            "not_found",
            f"{resource} 不存在。",
            status=404,
            details={"resource": resource, "id": resource_id},
        )


class RevisionConflict(DomainError):
    def __init__(self, expected: int, actual: int):
        super().__init__(
            "revision_conflict",
            "内容已在其他位置更新，请刷新后重试。",
            status=409,
            details={"expected_version": expected, "actual_version": actual},
        )

