from memory_center.core.completion import CompletionStatus, evaluate_completion, evaluate_walkthrough_completion


def test_complete_chain_tells_agent_to_stop_searching() -> None:
    status = evaluate_completion(
        expected_layers=("entry", "remote_feign", "server_controller"),
        observed_layers=("entry", "remote_feign", "server_controller"),
        terminal_anchor="ArticleController#moveArticle",
    )

    assert isinstance(status, CompletionStatus)
    assert status.state == "complete"
    assert status.missing_layers == ()
    assert status.terminal_anchor == "ArticleController#moveArticle"
    assert status.stop_reason == "all_expected_layers_observed"
    assert status.recommended_action == "use_current_evidence"


def test_partial_chain_lists_missing_layers() -> None:
    status = evaluate_completion(
        expected_layers=("entry", "remote_feign", "server_controller", "server_impl"),
        observed_layers=("entry", "remote_feign"),
        terminal_anchor="ArticleFeignClient#moveArticle",
    )

    assert status.state == "partial"
    assert status.missing_layers == ("server_controller", "server_impl")
    assert status.stop_reason == "missing_expected_layers"
    assert status.recommended_action == "fill_missing_layers"


def test_blocked_chain_has_no_observed_layers() -> None:
    status = evaluate_completion(
        expected_layers=("entry", "remote_feign"),
        observed_layers=(),
        terminal_anchor="",
    )

    assert status.state == "blocked"
    assert status.missing_layers == ("entry", "remote_feign")
    assert status.stop_reason == "no_layers_observed"
    assert status.recommended_action == "targeted_lookup_or_reindex"


def test_stale_chain_prioritizes_live_read_or_reindex() -> None:
    status = evaluate_completion(
        expected_layers=("entry", "remote_feign"),
        observed_layers=("entry", "remote_feign"),
        terminal_anchor="ArticleFeignClient#moveArticle",
        index_stale=True,
    )

    assert status.state == "stale"
    assert status.missing_layers == ()
    assert status.stop_reason == "index_not_fresh"
    assert status.recommended_action == "live_read_or_reindex"


def test_walkthrough_completion_detects_complete_chain_from_result() -> None:
    result = {
        "found": True,
        "target": {"class": "ArticleMoveService", "method": "move"},
        "local_service_continuations": [{"target": {"class": "ArticleAuditServiceImpl", "method": "recordMove"}}],
        "same_class_method_continuations": [{"target": {"class": "ArticleMoveService", "method": "validateMove"}}],
        "feign_continuations": [
            {
                "interface": "ArticleFeignClient",
                "method": "moveArticle",
                "server_walkthroughs": [
                    {
                        "controller": "ArticleController",
                        "method": "moveArticle",
                        "service_impl_continuations": [
                            {
                                "target": {"class": "ArticleWorkflowServiceImpl", "method": "moveArticle"},
                                "same_class_method_continuations": [
                                    {"target": {"class": "ArticleWorkflowServiceImpl", "method": "buildMoveContext"}}
                                ],
                            }
                        ],
                    }
                ],
            }
        ],
        "index_freshness": {"index_stale": False},
    }

    status = evaluate_walkthrough_completion(result)

    assert status["state"] == "complete"
    assert status["terminal_anchor"] == "ArticleWorkflowServiceImpl#buildMoveContext"
    assert status["missing_layers"] == []
    assert status["observed_layers"] == [
        "entry",
        "local_service",
        "same_class_method",
        "remote_feign",
        "server_controller",
        "server_impl",
        "bottom_method",
    ]
    assert status["recommended_action"] == "use_current_evidence"
