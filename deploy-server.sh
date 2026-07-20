#!/bin/bash
# 服务器端部署脚本
# 用法:
#   bash deploy-server.sh                    # 只更新镜像，不覆盖代码和配置
#   bash deploy-server.sh --force            # 强制用镜像中的代码覆盖本地
#   bash deploy-server.sh --force --force-config  # 代码+配置都强制覆盖
#   bash deploy-server.sh --force-config     # 只强制覆盖配置，不覆盖代码

set -e

FORCE=false
FORCE_CONFIG=false
for arg in "$@"; do
    case "$arg" in
        --force)         FORCE=true ;;
        --force-config)  FORCE_CONFIG=true ;;
    esac
done

echo "=== 加载镜像 ==="
docker load -i cmkb.tar

echo "=== 停止旧容器 ==="
docker compose down 2>/dev/null || true

# .env 如果是目录则删除（docker cp 需要）
if [ -d .env ]; then
    rm -rf .env
fi

echo "=== 从镜像拷贝文件 ==="
docker create --name tmp-deploy coremasterkb-app:latest

# 配置文件：--force-config 时才覆盖，否则仅补空
# 注意：域配置（domain_registry.yaml + scenario_packs/）住在 main_control_service/config 下，
# 归下面的「代码」分支管辖 —— 即受 --force 而非 --force-config 控制。
if [ "$FORCE_CONFIG" = true ]; then
    echo "=== --force-config: 覆盖 .env ==="
    docker cp tmp-deploy:/app/.env ./.env
else
    echo "=== 配置文件：仅补缺 ==="
    if [ ! -f .env ]; then
        docker cp tmp-deploy:/app/.env ./.env
    fi
fi

# 代码 + 工具脚本
if [ "$FORCE" = true ]; then
    echo "=== --force: 覆盖所有代码目录 ==="
    echo "!! 警告：这会一并重置 main_control_service/config/ 下的域配置"
    echo "!! （domain_registry.yaml、scenario_packs/、system/*.yaml）为镜像内版本。"
    for dir in knowledge_mining llm_service main_control_service mcp_server databases; do
        rm -rf "$dir"
        mkdir -p "$dir"
        docker cp "tmp-deploy:/app/$dir/." "./$dir/"
    done
    # 工具脚本随代码一起覆盖
    docker cp tmp-deploy:/app/reset_db.py ./reset_db.py
else
    echo "=== 仅拷贝空目录，已有代码不覆盖 ==="
    for dir in knowledge_mining llm_service main_control_service mcp_server databases; do
        if [ ! -d "$dir" ] || [ -z "$(ls -A $dir 2>/dev/null)" ]; then
            mkdir -p "$dir"
            docker cp "tmp-deploy:/app/$dir/." "./$dir/"
        fi
    done
    # reset_db.py 仅补缺
    if [ ! -f reset_db.py ]; then
        docker cp tmp-deploy:/app/reset_db.py ./reset_db.py
    fi
fi

docker rm tmp-deploy

echo "=== 启动容器 ==="
docker compose up -d

echo "=== 等待服务启动 ==="
sleep 10

echo "=== 服务状态 ==="
docker compose exec app supervisorctl status

echo ""
echo "=== 部署完成 ==="
echo "前端: http://$(hostname -I | awk '{print $1}')"
echo "修改配置后执行: docker compose exec app supervisorctl restart all"
