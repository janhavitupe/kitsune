from typing import Literal

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


class BranchUpdate(BaseModel):
    name: str | None = Field(default=None, pattern=BRANCH_NAME_PATTERN)
    kind: Literal["normal", "explore", "discarded"] | None = None


class Note(BaseModel):
    id: int
    commit_id: int
    kind: str  # artist | client
    transcript: str | None  # typed text, or the transcription of the recording (None until transcribed)
    summary: str | None
    audio_url: str | None
    created_at: str


class SearchResult(BaseModel):
    commit_id: int
    seq: int
    snippet: str  # the matching text with [brackets] around the hits
    reason: str


class SearchResponse(BaseModel):
    query: str
    relation: str | None  # before | after | when, for queries about a moment in the history
    parser: str  # spark | rules
    results: list[SearchResult]


class Repo(BaseModel):
    id: int
    name: str
    created_at: str


class RepoDetail(Repo):
    branches: list[Branch]


class ChangedRegion(BaseModel):
    label: str
    source: str  # "sam-3.1" for named regions, "change" for position-named change areas
    region_id: int | None
    changed_px: int
    changed_ratio: float
    image_share: float
    bbox: list[float]
    hints: list[str]
    polygons: list[list[list[float]]]


class Diff(BaseModel):
    id: int
    from_commit: int
    to_commit: int
    summary: str
    regions: list[ChangedRegion]
    changed_fraction: float
    resized: bool
    segmented: bool  # False until SAM regions exist for the newer version
    size: list[int]
    change_mask_url: str


class Region(BaseModel):
    id: int
    label: str
    bbox: list[float]
    area_px: int
    score: float | None
    source: str | None
    polygons: list[list[list[float]]]


class MergeChange(BaseModel):
    label: str
    bbox: list[float]
    hints: list[str]


class MergeConflict(MergeChange):
    index: int
    target_labels: list[str]  # what the target branch calls the area it changed there


class MergePlan(BaseModel):
    id: int
    status: str  # open | resolved | aborted
    source: str
    target: str
    source_head: int
    target_head: int
    base: int
    fast_forward: bool  # the target hasn't changed since the source branched off
    auto: list[MergeChange]  # changed on the source only: taken automatically
    conflicts: list[MergeConflict]  # changed on both sides: the artist picks


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
    note_count: int
    created_at: str
    image_url: str
    thumb_url: str
