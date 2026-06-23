@echo off
echo Weryfikacja integralności bota
python twb.py -i 2>NUL
if errorlevel 1 goto VERIFY_FAIL
python twb.py
goto :EOF
:VERIFY_FAIL
echo Wygląda na to, że bot nie uruchomił się.
echo Spróbuj uruchomić instalatora ponownie lub zainstaluj bota od nowa
echo Jeśli to nie rozwiąże problemu, utwórz problem na https://github.com/stefan2200/TWB/issues
pause
goto :EOF
