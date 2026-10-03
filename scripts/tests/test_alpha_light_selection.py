"""Compile and execute the actual standalone receiver selector and benchmark."""
import pathlib
import os
import shutil
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]

class AlphaLightSelectionTests(unittest.TestCase):
    def test_native_selection_and_benchmark(self):
        compiler = shutil.which("g++") or shutil.which("clang++")
        if not compiler:
            self.skipTest("A C++17 compiler is required")
        with tempfile.TemporaryDirectory(prefix="alpha-light-selection-") as directory:
            executable = pathlib.Path(directory) / "selection.exe"
            glm_include = pathlib.Path(os.environ.get("ALPHA_GLM_INCLUDE", "E:/BoxxyViewer-receiver-build/packages/include"))
            glm_args = []
            if (glm_include / "glm/glm.hpp").is_file():
                glm_args = ["-I", str(glm_include), "-DALPHA_TEST_GLM=1",
                            "-DGLM_FORCE_DEFAULT_ALIGNED_GENTYPES=1", "-DGLM_ENABLE_EXPERIMENTAL=1", "-DGLM_FORCE_SSE2=1"]
            subprocess.run([compiler, "-std=c++17", "-O2", "-Wall", "-Wextra", "-Werror", *glm_args,
                            "-I", str(ROOT / "indra/newview"),
                            str(pathlib.Path(__file__).with_name("alpha_light_selection_test.cpp")),
                            "-o", str(executable)], check=True)
            result = subprocess.run([str(executable)], check=True, capture_output=True, text=True)
            print(result.stdout)
            self.assertIn("Native selection checks passed", result.stdout)

if __name__ == "__main__":
    unittest.main()
