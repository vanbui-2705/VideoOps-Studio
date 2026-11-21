from core.application.submission_service import JobSubmissionService
from core.domain.models import Platform, VideoMetadata


class Workflow:
    def __init__(self):
        self.requests = []

    def submit(self, request):
        self.requests.append(request)
        return "job-view"


def test_story_submission_builds_exactly_one_content_source():
    workflow = Workflow()
    service = JobSubmissionService(workflow, max_remix_clips=3)

    result = service.submit_story(
        request_id="request-1",
        channel_id="tech_vn",
        source="script",
        content="A complete script",
        metadata=VideoMetadata(title="Draft"),
    )

    assert result == "job-view"
    request = workflow.requests[0]
    assert request.script == "A complete script"
    assert request.prompt is None


def test_remix_submission_parses_ordered_rows_and_requires_copyright():
    workflow = Workflow()
    service = JobSubmissionService(workflow, max_remix_clips=3)

    service.submit_remix(
        request_id="request-2",
        channel_id="tech_vn",
        rows=(
            ("https://example.com/one.mp4", 0, 10, 1.0, "fit", False),
            ("https://example.com/two.mp4", 2, 12, 1.5, "fill", True),
        ),
        copyright_confirmed=True,
        metadata=VideoMetadata(title="Remix"),
    )

    request = workflow.requests[0]
    assert tuple(clip.order for clip in request.clips) == (1, 2)
    assert request.clips[1].mirror is True


def test_submission_service_exposes_safe_job_refresh():
    class ReadWorkflow(Workflow):
        def get(self, job_id):
            return (job_id, (Platform.YOUTUBE,))

    assert JobSubmissionService(ReadWorkflow()).get("job-1") == (
        "job-1",
        (Platform.YOUTUBE,),
    )
