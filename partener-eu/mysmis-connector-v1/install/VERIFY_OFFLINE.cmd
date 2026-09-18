@echo off
setlocal
node "%~dp0..\PAYLOAD\native\install-preflight-cli.mjs" --bundle "%~dp0.." --attempt-id ATTEMPT-MCLENOVO-OFFLINE
exit /b %errorlevel%
