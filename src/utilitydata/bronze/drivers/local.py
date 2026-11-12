"""Compare files already on disk with the last good snapshot."""

from utilitydata.bronze.blobs import sha256_bytes
from utilitydata.bronze.drivers.protocol import CandidateFile, FetchRequest, FetchResult


def fetch_local(request: FetchRequest) -> FetchResult:
    """Hash the current files for one source. No network request is made."""
    if not request.previous:
        raise ValueError(f"{request.source.source_id} has no files in the previous snapshot")
    files: list[CandidateFile] = []
    differences: list[str] = []
    for previous in request.previous:
        content = request.read_current(previous.relative_path)
        digest = sha256_bytes(content)
        if digest != previous.sha256:
            differences.append(f"{previous.relative_path} snapshot {previous.sha256} current {digest}")
        elif len(content) != previous.byte_count:
            raise ValueError(f"Hash matches but byte count differs for {previous.relative_path}")
        files.append(CandidateFile(previous.relative_path, content))
    return FetchResult(not differences, tuple(files), tuple(differences))
