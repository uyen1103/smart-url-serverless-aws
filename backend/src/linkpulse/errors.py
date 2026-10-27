class ApiError(Exception):
    """Lỗi nghiệp vụ, được decorator `api_handler` đổi thành response JSON theo spec."""

    def __init__(self, status, code, message=None, reason=None, retry_after=None):
        super().__init__(code)
        self.status = status
        self.code = code
        self.message = message
        self.reason = reason
        self.retry_after = retry_after


MESSAGES = {
    "invalid_url": "URL không hợp lệ.",
    "blocked_domain": "Domain này đang bị chặn.",
    "invalid_alias": "Alias không hợp lệ.",
    "invalid_expires_in": "Thời hạn không hợp lệ.",
    "invalid_max_clicks": "Giới hạn click không hợp lệ.",
    "invalid_request": "Yêu cầu không hợp lệ.",
    "captcha_failed": "Xác minh captcha thất bại.",
    "alias_taken": "Alias này đã được sử dụng.",
    "unauthorized": "Thiếu định danh chủ sở hữu.",
    "forbidden": "Bạn không có quyền thực hiện thao tác này.",
    "not_found": "Không tìm thấy link.",
    "link_expired": "Link đã hết hạn.",
    "max_clicks_reached": "Link đã đạt giới hạn click.",
    "link_blocked": "Link đã bị chặn.",
    "link_suspicious": "Link cần được xem xét.",
    "rate_limited": "Bạn thao tác quá nhanh.",
    "internal_error": "Đã xảy ra lỗi, vui lòng thử lại sau.",
}


def err(status, code, reason=None, retry_after=None):
    return ApiError(status, code, MESSAGES.get(code), reason, retry_after)
