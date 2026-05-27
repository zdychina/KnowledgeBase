#!/bin/bash
# 本机构建并导出镜像
# 用法: bash deploy-build.sh

set -e
echo "=== 构建镜像 ==="
docker compose build

echo "=== 导出镜像 ==="
docker save coremasterkb-app:latest -o cmkb.tar

echo "=== 完成 ==="
ls -lh cmkb.tar
echo "将 cmkb.tar 传到服务器后，运行 bash deploy-server.sh"
