from __future__ import annotations

from pathlib import Path
import shutil

from novel_system.tools.llm_outlet_inventory import inventory_report, main as inventory_main


SRC_ROOT = Path(__file__).resolve().parents[1] / "src" / "novel_system"

EXPECTED_PRODUCTION_OUTLET_IDENTITIES = {
    "services/chapter_plan_llm.py::ChapterPlanService._run_structured_task::accounted_call",
    "services/literary_eval.py::LLMLiteraryCaseGenerator.__call__::accounted_call",
    "services/llm_accounting.py::_AccountedCompletionProbeExecution.generate_accounted::accounted_probe_transport",
    "services/llm_accounting.py::execute_accounted_completion_probe::accounted_call",
    "services/llm_task_runner.py::LLMNodeRunner.run::accounted_call",
    "services/llm_task_runner.py::LLMNodeRunner.run_task::accounted_call",
    "services/snowflake_workspace_llm.py::SnowflakeWorkspaceLLMService._run_structured_task::accounted_call",
    "services/style_reference/_llm_helper.py::call_llm_node::accounted_call",
    "services/style_reference/segmentation/llm.py::_classify_via_node::accounted_call",
}


def _write_modules(root: Path, modules: dict[str, str]) -> None:
    for relative_path, source in modules.items():
        path = root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source.strip() + "\n", encoding="utf-8")


def test_production_outlet_identity_set_is_locked_and_fully_unified() -> None:
    report = inventory_report(SRC_ROOT)

    assert report["summary"] == {
        "application_outlets": 9,
        "unified": 9,
        "unaccounted": 0,
    }
    assert {item["identity"] for item in report["outlets"]} == (
        EXPECTED_PRODUCTION_OUTLET_IDENTITIES
    )


def test_adversarial_completion_shapes_are_all_reported_and_cli_fails(
    tmp_path: Path,
    capsys,
) -> None:
    source_root = tmp_path / "novel_system"
    _write_modules(
        source_root,
        {
            "untyped_generate.py": '''
def direct_expression(client, raw):
    return client.generate(build_request(raw))

def keyword_without_annotation(client, raw):
    return client.generate(request=raw)

def passed_as_callable(client, raw):
    return invoke(client.generate, raw)

def bound_assignment(client, raw):
    generate = client.generate
    return generate(raw)
''',
            "llm_client_aliases.py": '''
def imported_class_alias(instance, raw):
    from novel_system.services.llm_client import LLMClient as ClientAlias
    return ClientAlias.generate(instance, raw)

def module_qualified_alias(instance, raw):
    import novel_system.services.llm_client as client_module
    return client_module.LLMClient.generate(instance, request=raw)
''',
            "httpx_function_aliases.py": '''
def imported_post_alias():
    from httpx import post as provider_post
    return provider_post("https://provider.example/v1/responses", json={})

def module_alias_post():
    import httpx as hx
    return hx.post("https://provider.example/v1/responses", json={})
''',
            "httpx_client_parameters.py": '''
import httpx as hx
from httpx import Client as SyncClient

def sync_parameter(client: SyncClient):
    return client.post("https://provider.example/v1/chat/completions", json={})

async def async_parameter(client: hx.AsyncClient):
    return await client.post("https://provider.example/v1/chat/completions", json={})

def bound_post(client: SyncClient):
    send = client.post
    return send("https://provider.example/v1/chat/completions", json={})
''',
        },
    )

    report = inventory_report(source_root)

    assert report["summary"] == {
        "application_outlets": 11,
        "unified": 0,
        "unaccounted": 11,
    }
    assert len({item["identity"] for item in report["outlets"]}) == 11
    assert {item["kind"] for item in report["outlets"]} == {
        "direct_generate",
        "completion_probe_httpx_post",
    }
    assert inventory_main(["--source-root", str(source_root), "--json"]) == 1
    assert '"unaccounted": 11' in capsys.readouterr().out


def test_new_same_named_generate_is_unaccounted_but_non_post_http_reads_are_safe(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "novel_system"
    _write_modules(
        source_root,
        {
            "new_business.py": '''
import httpx as hx

def new_business_call(service, project_id, body):
    return service.generate(project_id, body)

def model_and_health_reads():
    with hx.Client() as client:
        return client.get("https://provider.example/v1/models"), hx.get("https://provider.example/health")
'''
        },
    )

    report = inventory_report(source_root)

    assert report["summary"] == {
        "application_outlets": 1,
        "unified": 0,
        "unaccounted": 1,
    }
    assert report["outlets"][0]["kind"] == "direct_generate"


def test_adding_ninth_production_outlet_breaks_locked_identity_and_summary(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "novel_system"
    shutil.copytree(SRC_ROOT, source_root)
    _write_modules(
        source_root,
        {
            "services/new_completion_path.py": '''
from novel_system.services.llm_accounting import execute_accounted_call as accounted

def new_completion(session, client, request, context):
    return accounted(session, client, request, context)
'''
        },
    )

    report = inventory_report(source_root)
    identities = {item["identity"] for item in report["outlets"]}

    # 生产已知 outlet 现为 9 个（含已登记的 chapter_plan_llm）；临时新增 1 个 → 共 10，
    # 其中新增的那个未登记 → unaccounted=1，仍验证「新 outlet 打破锁定集」。
    assert report["summary"] == {
        "application_outlets": 10,
        "unified": 9,
        "unaccounted": 1,
    }
    assert identities != EXPECTED_PRODUCTION_OUTLET_IDENTITIES
    assert identities - EXPECTED_PRODUCTION_OUTLET_IDENTITIES == {
        "services/new_completion_path.py::new_completion::accounted_call"
    }


def test_function_and_module_accounting_aliases_are_detected_but_new_identities_default_unaccounted(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "novel_system"
    _write_modules(
        source_root,
        {
            "module_alias.py": '''
import novel_system.services.llm_accounting as ledger

def module_alias(session, client, request, context):
    return ledger.execute_accounted_call(session, client, request, context)
''',
            "function_alias.py": '''
def function_alias(session, client, request, context):
    from novel_system.services.llm_accounting import execute_accounted_call as accounted
    return accounted(session, client, request, context)
''',
        },
    )

    report = inventory_report(source_root)

    assert report["summary"] == {
        "application_outlets": 2,
        "unified": 0,
        "unaccounted": 2,
    }
    assert {item["kind"] for item in report["outlets"]} == {"accounted_call"}
