"""Compile actual alpha binding and light upload methods against recording stubs.

Run from the source tree: python scripts/tests/test_alpha_receiver_binding.py
Requires g++ and bundled build packages. Timing is CPU mock-stage overhead only:
no GL context, driver, GPU, actual textures, or viewer draw submission is present.
"""
from pathlib import Path
import shutil
import os
import subprocess
import tempfile


def function(source, signature):
    start = source.index(signature)
    brace = source.index('{', start)
    depth = 1
    end = brace + 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[start:end] + '\n'


def main():
    root = Path(__file__).resolve().parents[2]
    compiler = shutil.which('g++')
    if not compiler:
        raise SystemExit('g++ must be on PATH')
    includes = Path(os.environ.get('BOXXY_PACKAGES_INCLUDE', root / 'build-vc170-64/packages/include'))
    if not (includes / 'glm/glm.hpp').is_file():
        includes = Path('E:/BoxxyViewer/build-vc170-64/packages/include')
    if not (includes / 'glm/glm.hpp').is_file():
        raise SystemExit('Bundled GLM missing; set BOXXY_PACKAGES_INCLUDE to the packages/include directory')
    pipeline = (root / 'indra/newview/pipeline.cpp').read_text()
    render = (root / 'indra/llrender/llrender.cpp').read_text()
    methods = ''.join(function(pipeline, signature) for signature in (
        'bool LLPipeline::beginAlphaLights()',
        'void LLPipeline::endAlphaLights()',
        'void LLPipeline::restoreAlphaLightBaseline()',
        'void LLPipeline::bindAlphaLights(LLGLSLShader& shader, const LLAlphaLightSelection::Bounds& receiver)',
        'void LLPipeline::bindAlphaLightSelection(',
        'void LLPipeline::bindAlphaProjectors('))
    methods += ''.join(function(render, signature) for signature in (
        'void LLLightState::setDiffuse(const LLColor4& diffuse)',
        'void LLLightState::setAmbient(const LLColor4& ambient)',
        'void LLLightState::setSpecular(const LLColor4& specular)',
        'void LLLightState::setSize(F32 v)',
        'void LLLightState::setFalloff(F32 v)',
        'void LLLightState::setConstantAttenuation(const F32& atten)',
        'void LLLightState::setLinearAttenuation(const F32& atten)',
        'void LLLightState::setQuadraticAttenuation(const F32& atten)',
        'void LLLightState::setSpotCutoff(const F32& cutoff)',
        'void LLLightState::setSpotExponent(const F32& exponent)',
        'void LLLightState::setPosition(const LLVector4& position, const glm::mat4& modelview)',
        'void LLLightState::setSpotDirection(const LLVector3& direction, const glm::mat4& modelview)',
        'void LLRender::syncLightState()'))
    template = (Path(__file__).with_name('alpha_receiver_binding_test.cpp')).read_text()
    assert '// PRODUCTION_METHODS' in template
    header = (root / 'indra/llrender/llrender.h').read_text()
    invalidate = function(header, 'void invalidateLightState()')
    template = template.replace('// PRODUCTION_INVALIDATE_LIGHT_STATE', invalidate)
    with tempfile.TemporaryDirectory(prefix='boxxy-alpha-binding-') as directory:
        cpp, exe = Path(directory) / 'check.cpp', Path(directory) / 'check.exe'
        cpp.write_text(template.replace('// PRODUCTION_METHODS', methods))
        subprocess.run([compiler, '-std=c++17', '-O2', '-DGLM_ENABLE_EXPERIMENTAL',
                        '-I', str(includes),
                        '-I', str(root / 'indra/newview'), str(cpp), '-o', str(exe)], check=True)
        subprocess.run([str(exe)], check=True)
    print('PASS: production alpha binding, baseline restore, projector identity, camera transforms and light upload')


if __name__ == '__main__':
    main()
