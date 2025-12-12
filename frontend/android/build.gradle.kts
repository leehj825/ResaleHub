import org.gradle.api.tasks.compile.JavaCompile
import org.jetbrains.kotlin.gradle.tasks.KotlinCompile

allprojects {
    repositories {
        google()
        mavenCentral()
    }
}

val newBuildDir: Directory =
    rootProject.layout.buildDirectory
        .dir("../../build")
        .get()
rootProject.layout.buildDirectory.value(newBuildDir)

subprojects {
    val newSubprojectBuildDir: Directory = newBuildDir.dir(project.name)
    project.layout.buildDirectory.value(newSubprojectBuildDir)
}

subprojects {
    project.evaluationDependsOn(":app")
}

// Ensure Java/Kotlin compile targets are modern to avoid obsolete -source/-target warnings
subprojects {
    tasks.withType<JavaCompile>().configureEach {
        sourceCompatibility = "17"
        targetCompatibility = "17"
        // Suppress warnings about obsolete source/target options from plugin dependencies
        options.compilerArgs.addAll(listOf("-Xlint:-options"))
        // Do not set `options.release` for Android modules (AGP manages bootclasspath).
        // Only set `options.release` for non-Android JVM projects when supported.
        val isAndroidModule = try {
            project.plugins.hasPlugin("com.android.application") || project.plugins.hasPlugin("com.android.library")
        } catch (e: Throwable) {
            false
        }
        if (!isAndroidModule) {
            try {
                options.release.set(17)
            } catch (e: Exception) {
                // ignore when Gradle version doesn't support options.release
            }
        }
    }

    tasks.withType<org.jetbrains.kotlin.gradle.tasks.KotlinCompile>().configureEach {
        // Avoid compile-time references to newer Kotlin DSL symbols (KotlinJvmTarget, compilerOptions)
        // and instead try best-effort runtime reflection to set jvmTarget = "17" on kotlinOptions.
        try {
            @Suppress("UNCHECKED_CAST")
            val getter = this::class.java.getMethod("getKotlinOptions")
            val kopt = getter.invoke(this)
            if (kopt != null) {
                try {
                    val setJvm = kopt::class.java.getMethod("setJvmTarget", String::class.java)
                    setJvm.invoke(kopt, "17")
                } catch (e: NoSuchMethodException) {
                    // some plugin versions expose a jvmTarget property setter differently; try field access
                    try {
                        val field = kopt::class.java.getDeclaredField("jvmTarget")
                        field.isAccessible = true
                        field.set(kopt, "17")
                    } catch (_: Throwable) {
                        // give up; Gradle will report if nothing could be set
                    }
                }
            }
        } catch (_: Throwable) {
            // could not access kotlinOptions via reflection (very new plugin may not expose it) — nothing else to do safely here
        }
    }
}

tasks.register<Delete>("clean") {
    delete(rootProject.layout.buildDirectory)
}
