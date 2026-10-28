# Builds the app and publishes it to Watchd, where the app on the phone finds
# it the next time it opens ("Update ready") and installs it over Tailscale.
# Run from the android folder:  .\publish.ps1
$ErrorActionPreference = "Stop"
$env:JAVA_HOME = "C:\Program Files\Android\Android Studio\jbr"
.\gradlew.bat assembleRelease --console=plain -q
$out = "app\build\outputs\apk\release"
$meta = Get-Content "$out\output-metadata.json" -Raw | ConvertFrom-Json
$build = $meta.elements[0]
$dest = "..\backend\data\app"
New-Item -ItemType Directory -Force $dest | Out-Null
Copy-Item "$out\$($build.outputFile)" "$dest\watchd.apk" -Force
@{ version_code = $build.versionCode; version_name = $build.versionName } | ConvertTo-Json | Set-Content "$dest\version.json" -Encoding utf8
"Published Watchd $($build.versionName) ($([math]::Round((Get-Item "$dest\watchd.apk").Length / 1MB)) MB)"
