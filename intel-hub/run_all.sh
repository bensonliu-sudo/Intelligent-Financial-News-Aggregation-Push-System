# 一键启动 Intel Hub (main + web)
#命令:bash run_all.sh
# 激活 conda 环境
# 切换到项目目录
cd /Volumes/A/QT/intel-hub
source ~/anaconda3/bin/activate intel-hub310



# 同时启动 main 和 web
# main 用后台运行 (&)，web 前台运行
echo "启动 main 数据采集进程..."
python -m app.main --run-seconds 0 &

# 记住 main 的进程号，方便以后关闭
MAIN_PID=$!

echo "启动 web 前端..."
streamlit run app/web.py --server.port 8501

# 如果 web 退出了，就顺便把 main 杀掉
echo "关闭 main 进程 (PID=$MAIN_PID)..."
kill $MAIN_PID