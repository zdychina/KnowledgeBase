"""Run Mining API: python -m knowledge_mining.mining.api"""
from knowledge_mining.mining.api.app import app

if __name__ == "__main__":
    import uvicorn
    import os
    port = int(os.environ.get("MINING_API_PORT", "8901"))
    uvicorn.run(app, host="0.0.0.0", port=port)
