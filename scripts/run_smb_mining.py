"""Run the knowledge mining pipeline on data/test-input-smb-network.

Usage in PyCharm:
  1. Right-click this file -> Run 'run_smb_mining'
  2. In Run/Debug Configurations, ensure:
     - Working directory = project root (E:\\MyProjects\\KnowledgeBase)
     - Python interpreter = project venv with deps installed (pip install -e .)
"""
from __future__ import annotations

from knowledge_mining_zym.mining.jobs.run import run
from knowledge_mining_zym.mining.contracts.models import BatchParams


def main() -> None:
    result = run(
        input_path="data/test-input-smb-network",
        asset_core_db_path="data/smb_asset_core.sqlite",
        mining_runtime_db_path="data/smb_mining_runtime.sqlite",
        batch_params=BatchParams(
            default_source_type="folder_scan",
            default_document_type="deployment_guide",
            batch_scope={"products": ["SMB-Network"]},
            tags=["smb", "test"],
        ),
        # LLM Service (DeepSeek via local llm_service on :8900)
        llm_base_url="http://localhost:8900",
        llm_bypass_proxy=True,
        # Embedding (Zhipu BigModel embedding-3)
        embedding_api_key="bec7cc02fc88529bee532a07070f4e80.PbObZYZROyxvmtfq",
        embedding_model="embedding-3",
        embedding_base_url="https://open.bigmodel.cn/api/paas/v4",
        embedding_dimensions=2048,
    )
    print(result)


if __name__ == "__main__":
    main()
