#!/bin/bash
# 服务器端部署脚本
# 用法:
#   bash deploy-server.sh          # 只更新镜像，不覆盖代码
#   bash deploy-server.sh --force  # 强制用镜像中的代码覆盖本地

# 兼容 docker compose (v2)、docker-compose (v1)，或直接用 docker run
if docker compose version >/dev/null 2>&1; then
    DC="docker compose"
    USE_COMPOSE=true
elif command -v docker-compose >/dev/null 2>&1; then
    DC="docker-compose"
    USE_COMPOSE=true
else
    echo "[警告] 未找到 docker compose / docker-compose，将使用 docker run 启动"
    USE_COMPOSE=false
fi

set -e

FORCE=false
if [ "$1" = "--force" ]; then
    FORCE=true
fi

echo "=== 加载镜像 ==="
docker load -i cmkb.tar

echo "=== 停止旧容器 ==="
if [ "$USE_COMPOSE" = true ]; then
    $DC down 2>/dev/null || true
else
    docker stop cmkb 2>/dev/null || true
    docker rm cmkb 2>/dev/null || true
fi

# .env 如果是目录则删除
if [ -d .env ]; then
    rm -rf .env
fi
# domain_registry.yaml 如果是目录则删除
if [ -d domain_registry.yaml ]; then
    rm -rf domain_registry.yaml
fi

echo "=== 从镜像拷贝文件 ==="
docker create --name tmp-deploy coremasterkb-app:latest

# 配置文件：首次部署时从镜像拷贝，已存在则保留本地版本
if [ ! -f .env ] || [ "$FORCE" = true ]; then
    docker cp tmp-deploy:/app/.env ./.env
fi
if [ ! -f domain_registry.yaml ] || [ "$FORCE" = true ]; then
    docker cp tmp-deploy:/app/domain_registry.yaml ./domain_registry.yaml
fi

# 代码目录
if [ "$FORCE" = true ]; then
    echo "=== --force: 覆盖所有代码目录 ==="
    for dir in scenario_packs knowledge_mining llm_service main_control_service mcp_server databases; do
        rm -rf "$dir"
        mkdir -p "$dir"
        docker cp "tmp-deploy:/app/$dir/." "./$dir/"
    done
else
    echo "=== 仅拷贝空目录，已有代码不覆盖 ==="
    for dir in scenario_packs knowledge_mining llm_service main_control_service mcp_server databases; do
        if [ ! -d "$dir" ] || [ -z "$(ls -A $dir 2>/dev/null)" ]; then
            mkdir -p "$dir"
            docker cp "tmp-deploy:/app/$dir/." "./$dir/"
        fi
    done
fi

docker rm tmp-deploy

echo "=== 启动容器 ==="
if [ "$USE_COMPOSE" = true ]; then
    $DC up -d
else
    docker volume create cmkb_uploads 2>/dev/null || true
    docker volume create cmkb_control_data 2>/dev/null || true
    docker run -d \
        --name cmkb \
        --restart unless-stopped \
        --network host \
        -v cmkb_uploads:/app/uploads \
        -v cmkb_control_data:/app/data \
        -v "$(pwd)/.env:/app/.env" \
        -v "$(pwd)/domain_registry.yaml:/app/domain_registry.yaml" \
        -v "$(pwd)/scenario_packs:/app/scenario_packs" \
        -v "$(pwd)/knowledge_mining:/app/knowledge_mining" \
        -v "$(pwd)/llm_service:/app/llm_service" \
        -v "$(pwd)/main_control_service:/app/main_control_service" \
        -v "$(pwd)/mcp_server:/app/mcp_server" \
        -v "$(pwd)/databases:/app/databases" \
        -it \
        coremasterkb-app:latest
fi

echo "=== 等待服务启动 ==="
sleep 10

echo "=== 服务状态 ==="
docker exec cmkb supervisorctl status

echo ""
echo "=== 部署完成 ==="
echo "前端: http://$(hostname -I | awk '{print $1}')"
echo "修改配置后执行: docker exec cmkb supervisorctl restart all"