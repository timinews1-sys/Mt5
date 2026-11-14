[app]
title = DTEA
package.name = dtea
package.domain = org.timinews1
source.dir = .
source.include_exts = py,kv,json
source.exclude_dirs = .git,tests,__pycache__
version = 0.1.0
requirements = python3,kivy==2.3.1
orientation = portrait
fullscreen = 0
android.permissions = INTERNET
android.api = 35
android.minapi = 23
android.archs = arm64-v8a
android.accept_sdk_license = True
p4a.bootstrap = sdl2
p4a.python_version = 3.11

[buildozer]
log_level = 2
warn_on_root = 1
