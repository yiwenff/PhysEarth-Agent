"""The operator-only source block used by benchmark MCP processes."""

from integrations.physearth import service
from physearth import tools
from physearth.ingest import http


def test_testing_blocks_only_the_smrt_v1_paper_repository_and_derived_urls():
    http.configure_test_source_blocking(True)
    try:
        assert http.source_is_blocked("https://github.com/smrt-model/smrt_v1_paper/")
        assert http.source_is_blocked(
            "https://api.github.com/repos/smrt-model/smrt_v1_paper/git/trees/master?recursive=1"
        )
        assert http.source_is_blocked(
            "https://raw.githubusercontent.com/smrt-model/smrt_v1_paper/master/fig07.ipynb"
        )
        assert not http.source_is_blocked("https://github.com/smrt-model/smrt/")
        assert not http.source_is_blocked("https://gmd.copernicus.org/articles/11/2763/2018/")
        assert not http.source_is_blocked("https://github.com/another-owner/smrt_v1_paper/")
    finally:
        http.configure_test_source_blocking(False)


def test_testing_blocks_github_inspection_before_any_network_request():
    service.configure(testing=True)
    try:
        created = service.new_session(model="smrt")
        result = tools.call(
            "inspect_github_model_repo",
            {"url": "https://github.com/smrt-model/smrt_v1_paper/"},
            session=service.get_session(created["session_id"]),
        )
        assert result["status"] == "terminal_error"
        assert "testing source policy" in result["summary"]
    finally:
        service.configure(testing=False)


def test_service_health_reports_testing_source_block_without_listing_the_target():
    service.configure(testing=True)
    try:
        status = service.health()
        assert status["testing"] is True
        assert status["source_blocking"] is True
    finally:
        service.configure(testing=False)
