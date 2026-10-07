"""Opt-in integration test: launches the viewer and logs in with remembered credentials.

Run only when authorized to log in and temporarily change graphics/camera state.
No passwords or account files are read. Artifacts go to .logs/viewer-mcp.
"""
import asyncio
from datetime import timedelta
import json
import math
from pathlib import Path
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parents[2]


async def main():
    params = StdioServerParameters(command=sys.executable, args=[str(ROOT/'scripts/viewer_mcp/server.py')])
    async with stdio_client(params) as streams:
        async with ClientSession(*streams, read_timeout_seconds=timedelta(seconds=180)) as session:
            await session.initialize()
            async def call(name, args=None, error=False):
                result = await session.call_tool(name, args or {})
                if error:
                    assert result.isError, f"{name} should reject invalid input"
                    return None
                if result.isError:
                    raise RuntimeError(f"{name}: {result.content}")
                return result.structuredContent or json.loads(result.content[0].text)

            print('launch:', await call('viewer_launch'), flush=True)
            for _ in range(90):
                status = await call('viewer_status')
                if status['state'] == 'STATE_LOGIN_WAIT' or status['logged_in']:
                    break
                await asyncio.sleep(1)
            print('login:', await call('viewer_login'), flush=True)
            original = await call('camera_get')
            saved = await call('camera_save', {'label': 'live-test-original'})
            settings = (await call('graphics_settings'))['values']
            try:
                # Standalone capture must work without any camera/graphics writes.
                assert not original['locked'], 'Start live validation with the camera unlocked'
                await call('profile_start', {'frames': 20, 'warmup_frames': 30})
                for _ in range(180):
                    direct = await call('profile_result', {'save': False})
                    if direct['state'] == 'complete': break
                    assert direct['state'] not in ('failed', 'cancelled'), direct
                    await asyncio.sleep(.5)
                assert direct['state'] == 'complete', direct
                assert not direct['metadata']['camera']['locked'] and not direct['end_metadata']['camera']['locked']
                assert not (await call('viewer_status'))['camera_locked']
                assert (await call('graphics_settings'))['values'] == settings
                print('unlocked direct capture passed without camera or graphics writes', flush=True)
                pose = {k: original[k] for k in ('position_global','forward','up','vertical_fov_degrees','region_id')}
                pose['position_global'] = [original['position_global'][0]+.25, *original['position_global'][1:]]
                pose['vertical_fov_degrees'] = 55
                angle = math.radians(8)
                def rotate(v):
                    return [math.cos(angle)*v[0]-math.sin(angle)*v[1], math.sin(angle)*v[0]+math.cos(angle)*v[1], v[2]]
                pose['forward'] = rotate(original['forward'])
                pose['up'] = rotate(original['up'])
                await call('camera_set', pose)
                await asyncio.sleep(1)
                actual = await call('camera_get')
                assert max(abs(a-b) for a,b in zip(actual['position_global'],pose['position_global'])) < .001
                assert abs(actual['vertical_fov_degrees']-55) < .001
                assert max(abs(a-b) for a,b in zip(actual['forward'],pose['forward'])) < .0001
                await call('camera_set', {**pose, 'forward': [0,0,0]}, error=True)
                await call('graphics_set', {'values': {'RenderPCSSQuality': 99}}, error=True)
                await call('camera_restore', {'path': saved['path']})
                print('camera position/angle/FOV lock, restore and invalid-input checks passed', flush=True)
                await call('profile_start', {'frames': 20, 'warmup_frames': 30})
                await call('graphics_set', {'values': {'RenderPCSSQuality': 0}}, error=True)
                for _ in range(180):
                    result = await call('profile_result', {'save': False})
                    if result['state'] == 'complete': break
                    assert result['state'] not in ('failed','cancelled'), result
                    await asyncio.sleep(.5)
                assert result['state'] == 'complete', result
                result = await call('profile_result')
                assert result['completed_frames'] == 20
                assert result['gpu_ms']['frame']['median'] > 0
                assert result['render_submit_ms']['median'] > 0
                print('profile:', json.dumps({'artifact': result['artifact'], 'gpu_stages': list(result['gpu_ms']),
                      'gpu_frame_ms': result['gpu_ms']['frame'], 'render_submit_ms': result['render_submit_ms']}), flush=True)
                image = await session.call_tool('viewer_screenshot', {'label': 'live-test'})
                assert not image.isError and any(c.type == 'image' for c in image.content)
                print('MCP image returned', flush=True)
                # Exercise all seven enabled feature paths, even when the user's
                # baseline uses SMAA or has fog/GI off. These are smoke captures,
                # not optimization claims; viewer_restore restores the originals.
                await call('graphics_set', {'values': {'BoxxySSSEnabled': True, 'RenderPCSSEnabled': True,
                    'RenderShadowDetail': 2, 'RenderGTAOEnabled': True, 'RenderSSGIEnabled': True,
                    'RenderFSAAType': 3, 'RenderVolumeFog': True, 'RenderGroundFog': True}})
                print('benchmark:', await call('benchmark_start', {'frames': 10, 'warmup_frames': 10, 'repeats': 1}), flush=True)
                for _ in range(360):
                    progress = await call('benchmark_status')
                    if progress['state'] != 'running': break
                    if _%10 == 0: print('progress:', progress['current'], progress['completed_runs'], flush=True)
                    await asyncio.sleep(1)
                assert progress['state'] == 'complete', progress
                assert progress['settings_restored']
                print('suite:', json.dumps(progress), flush=True)
                # A second suite is cancelled to verify the restoration path live.
                await call('benchmark_start', {'features': ['PCSS'], 'frames': 180, 'warmup_frames': 120})
                await asyncio.sleep(.5)
                await call('benchmark_cancel')
                for _ in range(60):
                    cancelled = await call('benchmark_status')
                    if cancelled['state'] != 'running': break
                    await asyncio.sleep(.5)
                assert cancelled['state'] == 'cancelled' and cancelled['settings_restored'], cancelled
                print('live cancellation restored settings', flush=True)
            finally:
                await call('benchmark_cancel')
                for _ in range(60):
                    if (await call('benchmark_status'))['state'] != 'running': break
                    await asyncio.sleep(1)
                await call('profile_cancel')
                await call('viewer_restore')
                await call('camera_restore', {'path': saved['path']})
                await call('camera_release')
                final_settings = (await call('graphics_settings'))['values']
                for key in ('BoxxySSSEnabled','RenderPCSSEnabled','RenderShadowDetail','RenderGTAOEnabled',
                            'RenderSSGIEnabled','RenderFSAAType','RenderVolumeFog','RenderGroundFog','RenderVSyncEnable','BackgroundYieldTime','YieldTime'):
                    assert final_settings[key] == settings[key], (key,final_settings[key],settings[key])
            print('live validation passed; original settings and camera restored', flush=True)


if __name__ == '__main__':
    asyncio.run(main())
