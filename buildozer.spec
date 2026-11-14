[app]
title = DTEA
package.name = dtea
package.domain = org.timinews1
source.dir = .
source.include_exts = py,kv,json
source.exclude_dirs = .git,tests,__pycache__
version = 0.1.0
requirements = python3==3.12.10,hostpython3==3.12.10,kivy==2.3.1
orientation = all
fullscreen = 0
android.permissions = INTERNET
android.api = 35
android.minapi = 26
android.archs = arm64-v8a, armeabi-v7a, x86_64, x86
android.accept_sdk_license = True
p4a.bootstrap = sdl2

[buildozer]
log_level = 2
warn_on_root = 1
