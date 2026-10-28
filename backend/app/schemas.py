from pydantic import BaseModel, Field

BRANCH_NAME_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,63}$"


class RepoCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class Branch(BaseModel):
    id: int
    repo_id: int
    name: str
    head_commit_id: int | None
    kind: str
    created_at: str


class BranchCreate(BaseModel):
    name: str = Field(pattern=BRANCH_NAME_PATTERN)
    from_commit: int | None = None  # defaults to the head of main


class Repo(BaseModel):
    id: int
    name: str
    created_at: str


class RepoDetail(Repo):
    branches: list[Branch]


class Commit(BaseModel):
    id: int
    repo_id: int
    seq: int
    branch_id: int
    branch: str
    parent_id: int | None
    merge_parent_id: int | None
    blob_sha: str
    width: int
    height: int
    message: str | None
    auto_message: str | None
    origin: str
    origin_meta: dict | None
    analysis_status: str
    created_at: str
    image_url: str
    thumb_url: str
