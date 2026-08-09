from enum import StrEnum


class SenderType(StrEnum):
    USER = "user"
    MODERATOR = "moderator"


class MessageKind(StrEnum):
    TEXT = "text"
    PHOTO = "photo"


class ChatBucket(StrEnum):
    NEW = "new"
    ACTIVE = "active"
    OLD = "old"
    MINE = "mine"
