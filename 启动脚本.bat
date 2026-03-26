@echo off
%1 mshta vbscript:CreateObject("Shell.Application").ShellExecute("cmd.exe","/c %~s0 ::","","runas",1)(window.close)&&exit
cd /d "%~dp0"
echo 🚀 正在以实时优先级启动抢购脚本...
:: 启动 Python 并设置优先级
start /realtime python ultra_fast_clicker.py
exit