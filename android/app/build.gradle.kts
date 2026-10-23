plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("com.chaquo.python")
}

// 데스크톱 앱과 같은 소스를 쓴다: 저장소 최상위의 Python 모듈·web·skills를 빌드할 때 복사해 넣는다.
val repoRoot: File = rootDir.parentFile
val appVersion: String = Regex("""APP_VERSION = "([0-9.]+)"""")
    .find(File(repoRoot, "version.py").readText())!!.groupValues[1]
val versionParts = appVersion.split(".").map { it.toInt() }

val sharedPythonDir = layout.buildDirectory.dir("generated/sharedPython")
val sharedAssetsDir = layout.buildDirectory.dir("generated/sharedAssets")

val syncSharedPython by tasks.registering(Sync::class) {
    from(repoRoot) {
        include(
            "agent.py", "ai_memory.py", "api.py", "attachments.py", "certs.py", "documents.py", "main.py",
            "mcp_client.py", "office_mcp.py", "paper_mcp.py", "notion_mcp.py", "firecrawl_mcp.py",
            "po_note.py", "storage.py", "stt.py", "updates.py", "version.py",
            // 1.10: 커넥터·연결·도구 창
            "connectors.py", "oauth.py", "privacy.py", "secret_store.py", "workspace_api.py",
            "github_mcp.py", "google_mcp.py",
            // 1.10: 연구 워크스페이스
            "research_library.py", "research_mcp.py", "rag.py", "vector_store.py",
            // 1.10: 통합 메모리·인계·동기화
            "memory_store.py", "memory_mcp.py", "handoff.py", "sync.py",
            // 1.10: 에이전트 자동화(안드로이드에서는 쓸 수 없음으로 표시)·관측
            "runner_mcp.py",
        )
    }
    into(sharedPythonDir)
}

val syncSharedAssets by tasks.registering(Sync::class) {
    from(File(repoRoot, "web")) { into("web") }
    from(File(repoRoot, "skills")) { into("skills") }
    from(File(repoRoot, "licenses")) { into("licenses") }
    from(repoRoot) { include("LICENSE", "THIRD_PARTY_NOTICES.md") }
    into(sharedAssetsDir)
}

android {
    namespace = "io.github.bj0322.poschat"
    compileSdk = 34

    defaultConfig {
        applicationId = "io.github.bj0322.poschat"
        minSdk = 24
        targetSdk = 34
        versionCode = versionParts[0] * 10000 + versionParts[1] * 100 + versionParts[2]
        versionName = appVersion
        ndk {
            // 휴대폰(arm64)과 에뮬레이터(x86_64)
            abiFilters += listOf("arm64-v8a", "x86_64")
        }
        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
    }

    signingConfigs {
        // 모든 빌드를 같은 키로 서명해야 새 APK를 지우지 않고 덮어 설치할 수 있다.
        // 저장소에 들어 있는 공용 키이므로, 공개 배포(Play 스토어 등)에는 따로 보관한 키를 쓰세요.
        create("shared") {
            storeFile = file("poschat-shared.keystore")
            storePassword = "poschat"
            keyAlias = "poschat"
            keyPassword = "poschat"
        }
    }

    buildTypes {
        getByName("debug") {
            signingConfig = signingConfigs.getByName("shared")
        }
        getByName("release") {
            isMinifyEnabled = false
            signingConfig = signingConfigs.getByName("shared")
        }
    }

    buildFeatures {
        buildConfig = true
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions {
        jvmTarget = "17"
    }

    sourceSets["main"].assets.srcDir(sharedAssetsDir)

    lint {
        checkReleaseBuilds = false  // CI 시간을 줄인다. 동작 검증은 에뮬레이터 계측 테스트가 한다
    }
}

chaquopy {
    defaultConfig {
        version = "3.11"
        pip {
            install("-r", "requirements-android.txt")
        }
    }
    sourceSets {
        getByName("main") {
            srcDir(sharedPythonDir)
        }
    }
}

tasks.named("preBuild") { dependsOn(syncSharedPython, syncSharedAssets) }
// Chaquopy·AGP의 소스 병합 작업이 복사보다 먼저 돌지 않게 한다.
tasks.configureEach {
    if (name.contains("Python", ignoreCase = true) && name.startsWith("merge")) dependsOn(syncSharedPython)
    if (name.endsWith("Assets") && name.startsWith("merge")) dependsOn(syncSharedAssets)
}

dependencies {
    implementation("androidx.core:core-ktx:1.13.1")
    implementation("androidx.activity:activity-ktx:1.9.2")
    implementation("androidx.webkit:webkit:1.11.0")

    androidTestImplementation("androidx.test:core:1.6.1")
    androidTestImplementation("androidx.test.ext:junit:1.2.1")
    androidTestImplementation("androidx.test:runner:1.6.2")
}
