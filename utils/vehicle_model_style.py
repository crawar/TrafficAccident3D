"""Shared Three.js vehicle model script for generated scene and preview.

Vehicle bodies are pre-authored GLB models (see `glbmodels/`) embedded as
base64 and parsed at runtime with `THREE.GLTFLoader.parse()`; this module no
longer builds vehicle geometry procedurally. Two simplifications are in
effect by design: the GLB's own materials/colors are used as-is (no aerial
photo color sampling), and composite vehicles (tractor+trailer, box/tank/
flatbed trucks) are scaled using a single merged width/length/height instead
of separate cab/cargo dimensions.
"""

import base64
import json
import os

from core.vehicle_model_settings import load_vehicle_model_settings
from utils.app_paths import app_path

VEHICLE_MODEL_PLACEHOLDER = "<!-- VEHICLE_MODEL_SCRIPT -->"

_GLB_DIR = app_path("glbmodels")

# Chinese vehicle type -> (glb filename, yaw applied about Y so the model's
# real front faces +Z, node-name substrings to drop as junk geometry). Yaw
# and skip lists were determined by visually/numerically inspecting each GLB
# (material names, node names, UV-mapped texture atlases) with a throwaway
# diagnostic script (see tools/inspect_glb.py).
VEHICLE_GLB_CALIBRATION = {
    "小客车": {"file": "01_sedan.glb", "yaw": 0, "skipNodeNames": ["plane.055"]},
    # Replacement GLB already faces +Z (front lights / wiper / dashboard at +Z).
    "大巴车": {"file": "02_bus.glb", "yaw": 0, "skipNodeNames": []},
    # "Plane001" is a stray oversized flat quad (material "RootNode", ~185x297
    # vs. the truck body's own ~90x211) baked into this GLB - probably a leftover
    # ground/shadow-decal plane from the original 3ds Max/Blender scene. Left
    # in, it dominates the model's bounding box on x/z, so baseSize ends up far
    # larger than the real body and the width/length -> scale conversion in
    # createVehicle() shrinks the visible truck well below VEHICLE_SPECS.
    "轻型栏板货车": {"file": "03_light_stake_truck.glb", "yaw": 0, "skipNodeNames": ["Plane001"]},
    "大型栏板货车": {"file": "04_large_stake_truck.glb", "yaw": 270, "skipNodeNames": []},
    "大型罐式货车": {"file": "05_tank_truck.glb", "yaw": 0, "skipNodeNames": []},
    # Replacement GLB faces the opposite direction from the previous asset.
    "大型厢式货车": {"file": "06_box_truck.glb", "yaw": 0, "skipNodeNames": []},
    "牵引车及挂车": {"file": "07_tractor_trailer.glb", "yaw": 0, "skipNodeNames": []},
    "商务车": {"file": "08_business_van.glb", "yaw": 0, "skipNodeNames": []},
}

_glb_base64_cache = {}


def _load_glb_base64(filename: str) -> str:
    """Read + base64-encode a GLB file; cache by filename + mtime."""
    path = os.path.join(_GLB_DIR, filename)
    mtime = os.path.getmtime(path)
    cached = _glb_base64_cache.get(filename)
    if cached is not None and cached[0] == mtime:
        return cached[1]
    with open(path, "rb") as f:
        encoded = base64.b64encode(f.read()).decode("ascii")
    _glb_base64_cache[filename] = (mtime, encoded)
    return encoded


def get_vehicle_model_script(used_types=None) -> str:
    """Return the inline Three.js vehicle model script.

    `used_types` (an iterable of Chinese vehicle type names) restricts which
    GLB models get base64-embedded, keeping per-report HTML size down. Pass
    None (the default, used by the all-types preview dialog) to embed every
    known type.
    """
    settings = load_vehicle_model_settings()
    specs_json = json.dumps(settings["vehicleSpecs"], ensure_ascii=False)
    lane_width_json = json.dumps(settings["laneWidth"], ensure_ascii=False)
    emergency_lane_width_json = json.dumps(
        settings["emergencyLaneWidth"], ensure_ascii=False
    )
    outline_width_json = json.dumps(settings["outlineWidth"], ensure_ascii=False)

    wanted_types = set(used_types) if used_types else set(VEHICLE_GLB_CALIBRATION.keys())
    glb_data = {}
    calibration = {}
    for vtype, info in VEHICLE_GLB_CALIBRATION.items():
        if vtype not in wanted_types:
            continue
        glb_data[vtype] = _load_glb_base64(info["file"])
        calibration[vtype] = {"yaw": info["yaw"], "skipNodeNames": info["skipNodeNames"]}
    glb_data_json = json.dumps(glb_data, ensure_ascii=False)
    calibration_json = json.dumps(calibration, ensure_ascii=False)

    return r"""
        // 3. Dynamic vehicles (+Z is front). Bodies come from pre-authored GLB
        // models (embedded as base64 below) instead of procedural geometry.
        var VEHICLE_SPECS = __VEHICLE_SPECS__;
        let VEHICLE_LANE_WIDTH = __VEHICLE_LANE_WIDTH__;
        let VEHICLE_EMERGENCY_LANE_WIDTH = __VEHICLE_EMERGENCY_LANE_WIDTH__;
        var SCENE_OUTLINE_WIDTH = __SCENE_OUTLINE_WIDTH__;
        var VEHICLE_GLB_DATA = __VEHICLE_GLB_DATA__;
        var VEHICLE_GLB_CALIBRATION = __VEHICLE_GLB_CALIBRATION__;
        // Preview dialog defaults on; accident scene forces false so overlays stay hidden.
        var SHOW_VEHICLE_MAPPING = true;
        var VEHICLE_MAPPING_BREATH_MATERIALS = [];

        const VEHICLE_EDGE_MATERIAL = new THREE.MeshBasicMaterial({
            color: 0x000000,
            transparent: false,
            opacity: 1,
            depthTest: true
        });

        function setSceneOutlineWidth(width) {
            const nextWidth = Number(width);
            if (!Number.isFinite(nextWidth) || nextWidth <= 0) return;
            SCENE_OUTLINE_WIDTH = nextWidth;
            VEHICLE_EDGE_MATERIAL.needsUpdate = true;
            if (typeof MARKER_EDGE_MATERIAL !== 'undefined') {
                MARKER_EDGE_MATERIAL.needsUpdate = true;
            }
        }

        function setShowVehicleMapping(show) {
            SHOW_VEHICLE_MAPPING = !!show;
            if (typeof window !== 'undefined' && typeof window.onShowVehicleMappingChanged === 'function') {
                window.onShowVehicleMappingChanged(SHOW_VEHICLE_MAPPING);
            }
        }

        function updateVehicleMappingBreath(nowMs) {
            if (!SHOW_VEHICLE_MAPPING || !VEHICLE_MAPPING_BREATH_MATERIALS.length) return;
            const t = (typeof nowMs === 'number' ? nowMs : performance.now()) * 0.001;
            const opacity = 0.375 + 0.125 * Math.sin(t * 2.0);
            for (let i = 0; i < VEHICLE_MAPPING_BREATH_MATERIALS.length; i++) {
                const mat = VEHICLE_MAPPING_BREATH_MATERIALS[i];
                if (mat) mat.opacity = opacity;
            }
        }

        window.setShowVehicleMapping = setShowVehicleMapping;
        window.updateVehicleMappingBreath = updateVehicleMappingBreath;

        function sceneOutlineRadius() {
            return Math.max(0.001, Number(SCENE_OUTLINE_WIDTH || 1) * 0.003);
        }

        function createSceneEdgeOutline(mesh, thresholdAngle, edgeMaterial) {
            if (!mesh || !mesh.geometry) return null;
            const edgeGeo = new THREE.EdgesGeometry(mesh.geometry, thresholdAngle);
            const pos = edgeGeo.attributes.position;
            if (!pos || pos.count < 2) {
                edgeGeo.dispose();
                return null;
            }
            const group = new THREE.Group();
            group.userData.isOutline = true;
            group.userData.ignoreLiabilityBounds = true;
            group.userData.ignoreVehicleRaycast = true;
            const radius = sceneOutlineRadius();
            const start = new THREE.Vector3();
            const end = new THREE.Vector3();
            const mid = new THREE.Vector3();
            const dir = new THREE.Vector3();
            const up = new THREE.Vector3(0, 1, 0);
            for (let i = 0; i < pos.count; i += 2) {
                start.fromBufferAttribute(pos, i);
                end.fromBufferAttribute(pos, i + 1);
                dir.subVectors(end, start);
                const len = dir.length();
                if (len <= 0.0001) continue;
                mid.addVectors(start, end).multiplyScalar(0.5);
                const geo = new THREE.CylinderGeometry(radius, radius, len, 8, 1, true);
                const edge = new THREE.Mesh(geo, edgeMaterial);
                edge.userData.isOutline = true;
                edge.userData.ignoreLiabilityBounds = true;
                edge.userData.ignoreVehicleRaycast = true;
                edge.position.copy(mid);
                edge.quaternion.setFromUnitVectors(up, dir.normalize());
                edge.renderOrder = 3;
                group.add(edge);
            }
            edgeGeo.dispose();
            return group;
        }

        function createSceneOutlineSegments(segments, edgeMaterial) {
            if (!segments || !segments.length) return null;
            const group = new THREE.Group();
            group.userData.isOutline = true;
            group.userData.ignoreLiabilityBounds = true;
            group.userData.ignoreVehicleRaycast = true;
            const radius = sceneOutlineRadius();
            const start = new THREE.Vector3();
            const end = new THREE.Vector3();
            const mid = new THREE.Vector3();
            const dir = new THREE.Vector3();
            const up = new THREE.Vector3(0, 1, 0);
            segments.forEach(function (seg) {
                start.set(seg.a.x, seg.a.y, seg.a.z);
                end.set(seg.b.x, seg.b.y, seg.b.z);
                dir.subVectors(end, start);
                const len = dir.length();
                if (len <= 0.0001) return;
                mid.addVectors(start, end).multiplyScalar(0.5);
                const geo = new THREE.CylinderGeometry(radius, radius, len, 8, 1, true);
                const edge = new THREE.Mesh(geo, edgeMaterial);
                edge.userData.isOutline = true;
                edge.userData.ignoreLiabilityBounds = true;
                edge.userData.ignoreVehicleRaycast = true;
                edge.position.copy(mid);
                edge.quaternion.setFromUnitVectors(up, dir.normalize());
                edge.renderOrder = 3;
                group.add(edge);
            });
            return group.children.length ? group : null;
        }

        // Optional, guarded reflection probe. Builds a lightweight studio-gradient
        // environment with PMREM so the GLB paint/glass/chrome materials pick up
        // soft highlights. If no global renderer (or PMREM) is available it
        // silently no-ops.
        function buildVehicleEnvTexture() {
            const c = document.createElement('canvas');
            c.width = 32;
            c.height = 128;
            const ctx = c.getContext('2d');
            const g = ctx.createLinearGradient(0, 0, 0, 128);
            g.addColorStop(0.0, '#eef4fb');
            g.addColorStop(0.42, '#c2cedd');
            g.addColorStop(0.5, '#9aa6b4');
            g.addColorStop(0.58, '#5f6772');
            g.addColorStop(1.0, '#2a2e34');
            ctx.fillStyle = g;
            ctx.fillRect(0, 0, 32, 128);
            const tex = new THREE.CanvasTexture(c);
            tex.mapping = THREE.EquirectangularReflectionMapping;
            tex.needsUpdate = true;
            return tex;
        }

        let VEHICLE_ENV_MAP = undefined;
        function getVehicleEnvMap() {
            if (VEHICLE_ENV_MAP !== undefined) return VEHICLE_ENV_MAP;
            VEHICLE_ENV_MAP = null;
            try {
                if (typeof renderer === 'undefined' || !renderer || typeof THREE.PMREMGenerator !== 'function') {
                    return VEHICLE_ENV_MAP;
                }
                const pmrem = new THREE.PMREMGenerator(renderer);
                const equirect = buildVehicleEnvTexture();
                VEHICLE_ENV_MAP = pmrem.fromEquirectangular(equirect).texture;
                equirect.dispose();
                pmrem.dispose();
            } catch (e) {
                VEHICLE_ENV_MAP = null;
            }
            return VEHICLE_ENV_MAP;
        }

        // ---- GLB loading / calibration / template cache -----------------------
        const VEHICLE_TEMPLATE_CACHE = {};
        let VEHICLE_MODELS_READY = false;
        const VEHICLE_MODELS_READY_CALLBACKS = [];

        // Runs `fn` once every embedded GLB has been parsed and calibrated. Calls
        // `fn` synchronously if models are already ready. This is the only gate
        // needed around code that calls createVehicle(), since GLTF parsing /
        // texture decoding is inherently asynchronous.
        function whenVehicleModelsReady(fn) {
            if (typeof fn !== 'function') return;
            if (VEHICLE_MODELS_READY) {
                fn();
            } else {
                VEHICLE_MODELS_READY_CALLBACKS.push(fn);
            }
        }

        function resolveVehicleModelsReady() {
            VEHICLE_MODELS_READY = true;
            const callbacks = VEHICLE_MODELS_READY_CALLBACKS.slice();
            VEHICLE_MODELS_READY_CALLBACKS.length = 0;
            callbacks.forEach(function (fn) {
                try { fn(); } catch (e) { console.error('whenVehicleModelsReady callback failed', e); }
            });
        }

        function base64ToArrayBuffer(base64) {
            const binary = atob(base64);
            const bytes = new Uint8Array(binary.length);
            for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
            return bytes.buffer;
        }

        // Normalizes a freshly-parsed GLTF scene into a reusable template: drops
        // junk nodes (backdrop planes / stray lights), adds a soft env-map
        // reflection to every material, then recenters + auto-scales the whole
        // model (after applying its calibration yaw) so it measures exactly
        // VEHICLE_SPECS[type].width/height/length with its wheels sitting on
        // y = 0 and its footprint centered on x/z = 0.
        // three.js r128's GLTFLoader can't honor a texture's non-zero UV
        // channel ("Custom UV set N for texture ... not yet supported"
        // warning) - it still assigns the texture but the built-in shader
        // always samples map/normalMap/roughnessMap/metalnessMap/emissiveMap
        // with UV0, so any of those authored against UV1+ render warped/
        // moire. Look up each material's raw glTF definition (via the
        // parser the loader hands back) and drop maps whose texCoord isn't
        // 0, so they fall back to a flat default instead of garbled.
        const MISMATCHED_UV_MAP_DEFS = {
            map: 'baseColorTexture',
            normalMap: 'normalTexture',
            roughnessMap: 'metallicRoughnessTexture',
            metalnessMap: 'metallicRoughnessTexture',
            emissiveMap: 'emissiveTexture'
        };
        function stripMismatchedUvMaps(gltf) {
            const parser = gltf.parser;
            const json = parser && parser.json;
            if (!json || !json.materials) return;
            const seen = new Set();
            gltf.scene.traverse(function (node) {
                if (!node.isMesh) return;
                const materials = Array.isArray(node.material) ? node.material : [node.material];
                materials.forEach(function (mat) {
                    if (!mat || seen.has(mat)) return;
                    seen.add(mat);
                    const assoc = parser.associations.get(mat);
                    const materialDef = assoc && assoc.index !== undefined ? json.materials[assoc.index] : null;
                    if (!materialDef) return;
                    Object.keys(MISMATCHED_UV_MAP_DEFS).forEach(function (mapKey) {
                        const defKey = MISMATCHED_UV_MAP_DEFS[mapKey];
                        const texDef = defKey === 'normalTexture' || defKey === 'occlusionTexture'
                            ? materialDef[defKey]
                            : (materialDef.pbrMetallicRoughness || {})[defKey];
                        if (texDef && texDef.texCoord) mat[mapKey] = null;
                    });
                    mat.needsUpdate = true;
                });
            });
        }

        function prepareVehicleTemplate(type, gltf) {
            stripMismatchedUvMaps(gltf);
            const gltfScene = gltf.scene;
            const calib = VEHICLE_GLB_CALIBRATION[type] || { yaw: 0, skipNodeNames: [] };
            // GLTFLoader strips punctuation from node names (e.g. "Plane.055"
            // becomes "Plane055_0"), so compare on alphanumeric-only, lowercased
            // strings rather than raw substrings.
            const normalizeName = function (s) { return String(s || '').toLowerCase().replace(/[^a-z0-9]/g, ''); };
            const skipNames = (calib.skipNodeNames || []).map(normalizeName);

            const junk = [];
            gltfScene.traverse(function (node) {
                const name = normalizeName(node.name);
                const isJunkName = skipNames.some(function (s) { return s && name.indexOf(s) !== -1; });
                if (isJunkName || node.isLight) junk.push(node);
            });
            junk.forEach(function (node) {
                if (node.parent) node.parent.remove(node);
            });

            // Fine repeating body-panel textures (louvers, tank ribbing,
            // diamond-plate, etc.) alias into a moire pattern when viewed at
            // an angle with only mipmapping; a modest anisotropy level fixes
            // this cheaply without needing the renderer's max-anisotropy cap
            // (three.js clamps to whatever the GPU actually supports).
            const TEXTURE_MAP_KEYS = ['map', 'normalMap', 'roughnessMap', 'metalnessMap', 'aoMap', 'emissiveMap', 'bumpMap', 'alphaMap'];
            const env = getVehicleEnvMap();
            gltfScene.traverse(function (node) {
                if (!node.isMesh) return;
                node.castShadow = true;
                node.receiveShadow = true;
                const materials = Array.isArray(node.material) ? node.material : [node.material];
                materials.forEach(function (mat) {
                    if (!mat) return;
                    TEXTURE_MAP_KEYS.forEach(function (key) {
                        const tex = mat[key];
                        if (tex && tex.anisotropy < 4) tex.anisotropy = 4;
                    });
                    if (!mat.envMap && env) {
                        mat.envMap = env;
                        mat.envMapIntensity = 0.35;
                    }
                    mat.needsUpdate = true;
                });
            });

            const wrapper = new THREE.Group();
            wrapper.add(gltfScene);
            wrapper.rotation.y = calib.yaw * Math.PI / 180;

            const pivot = new THREE.Group();
            pivot.add(wrapper);
            pivot.updateMatrixWorld(true);

            const box = new THREE.Box3().setFromObject(wrapper);
            if (!box.isEmpty()) {
                const size = box.getSize(new THREE.Vector3());
                const centerX = (box.min.x + box.max.x) / 2;
                const centerZ = (box.min.z + box.max.z) / 2;
                wrapper.position.set(-centerX, -box.min.y, -centerZ);

                // Store the model's *unscaled* footprint instead of baking a
                // fixed scale into the cached template. VEHICLE_SPECS can change
                // at runtime (the preview dialog's size fields, live edits), so
                // the width/height/length -> scale conversion has to happen on
                // every createVehicle() call against the *current* spec, not
                // once here at first-load time.
                if (size.x > 1e-4 && size.y > 1e-4 && size.z > 1e-4) {
                    pivot.userData.baseSize = { x: size.x, y: size.y, z: size.z };
                }
            }
            pivot.updateMatrixWorld(true);
            return pivot;
        }

        function loadVehicleModels() {
            const types = Object.keys(VEHICLE_GLB_DATA);
            if (!types.length || typeof THREE.GLTFLoader !== 'function') {
                resolveVehicleModelsReady();
                return;
            }
            const loader = new THREE.GLTFLoader();
            let pending = types.length;
            function settleOne() {
                pending -= 1;
                if (pending <= 0) resolveVehicleModelsReady();
            }
            types.forEach(function (type) {
                let buffer;
                try {
                    buffer = base64ToArrayBuffer(VEHICLE_GLB_DATA[type]);
                } catch (e) {
                    console.error('Failed to decode embedded GLB for', type, e);
                    settleOne();
                    return;
                }
                loader.parse(buffer, '', function (gltf) {
                    try {
                        VEHICLE_TEMPLATE_CACHE[type] = prepareVehicleTemplate(type, gltf);
                    } catch (e) {
                        console.error('Failed to prepare vehicle template for', type, e);
                    }
                    settleOne();
                }, function (error) {
                    console.error('Failed to load GLB for', type, error);
                    settleOne();
                });
            });
        }
        loadVehicleModels();

        // Deep-clone materials per vehicle, while preserving material sharing
        // inside that vehicle. A GLB commonly reuses one paint material on many
        // meshes; cloning it separately for every mesh would make recoloring only
        // affect one body panel. Different vehicles still get isolated materials,
        // so clipping/recolor changes cannot leak between vehicle instances.
        function cloneVehicleModel(template) {
            const clone = template.clone(true);
            const materialClones = new Map();
            function cloneMaterial(mat) {
                if (!mat) return mat;
                if (!materialClones.has(mat)) {
                    materialClones.set(mat, mat.clone());
                }
                return materialClones.get(mat);
            }
            clone.traverse(function (node) {
                if (!node.isMesh || !node.material) return;
                node.material = Array.isArray(node.material)
                    ? node.material.map(cloneMaterial)
                    : cloneMaterial(node.material);
            });
            return clone;
        }

        // GLB meshes have no consistent "isWheel" naming, so wheel/magnetic-snap
        // points are synthesized from spec.wheels (z positions).
        //
        // wheelRadius = half of the upright tire's ground-projection length
        // (standing on the road, not lying flat). Tire thickness (cylinder
        // height) is fixed: 0.27 m for passenger cars, 0.30 m for larger types.
        // Pad centers stay inside the blue body footprint, flush with the
        // outer side edges (tires are tangent to the vehicle outline).
        function _tireMappingDims(spec) {
            const width = Number(spec.width) || 0;
            const length = Number(spec.length) || 0;
            const radius = Math.max(0.05, Number(spec.wheelRadius) || 0.3);
            const kind = String(spec.kind || '');
            const thickness = (kind === 'passenger') ? 0.27 : 0.3;
            return {
                width: width,
                length: length,
                radius: radius,
                thickness: thickness,
                tireLength: radius * 2
            };
        }

        function _tirePadCenter(spec, z, side) {
            const d = _tireMappingDims(spec);
            const halfThick = d.thickness * 0.5;
            const sideX = Math.max(0, d.width * 0.5 - halfThick);
            const halfTireLen = d.tireLength * 0.5;
            const maxZ = Math.max(0, d.length * 0.5 - halfTireLen);
            const zVal = Number(z);
            const zClamped = Math.max(
                -maxZ,
                Math.min(maxZ, Number.isFinite(zVal) ? zVal : 0)
            );
            return {
                x: side * sideX,
                z: zClamped,
                y: d.radius,
                thickness: d.thickness,
                tireLength: d.tireLength,
                radius: d.radius
            };
        }

        function addSyntheticWheelMarkers(group, spec) {
            (spec.wheels || []).forEach(function (z) {
                [-1, 1].forEach(function (side) {
                    const pose = _tirePadCenter(spec, z, side);
                    const marker = new THREE.Object3D();
                    marker.position.set(pose.x, pose.y, pose.z);
                    marker.userData.isWheel = true;
                    marker.userData.ignoreVehicleRaycast = true;
                    marker.userData.ignoreLiabilityBounds = true;
                    group.add(marker);
                });
            });
        }

        function _markMappingOverlay(obj) {
            obj.userData.isMappingOverlay = true;
            obj.userData.ignoreVehicleRaycast = true;
            obj.userData.ignoreLiabilityBounds = true;
        }

        // Blue footprint + green upright-tire pads for preview "显示映射".
        // Measurement uses the same pad centers as these overlays.
        function addVehicleMappingOverlays(group, spec) {
            if (!SHOW_VEHICLE_MAPPING) return;
            const dims = _tireMappingDims(spec);
            if (!(dims.width > 0 && dims.length > 0)) return;

            // Preview rebuilds a single vehicle; clear stale breath materials first.
            VEHICLE_MAPPING_BREATH_MATERIALS = [];

            const overlayRoot = new THREE.Group();
            _markMappingOverlay(overlayRoot);

            const blueMat = new THREE.MeshBasicMaterial({
                color: 0x1e88e5,
                transparent: true,
                opacity: 0.75,
                depthWrite: false,
                side: THREE.DoubleSide
            });
            // PlaneGeometry(width, height) in XY; after -90° X rot → world X/Z.
            const blueGeo = new THREE.PlaneGeometry(dims.width, dims.length);
            const blueMesh = new THREE.Mesh(blueGeo, blueMat);
            blueMesh.rotation.x = -Math.PI / 2;
            blueMesh.position.y = 0.015;
            blueMesh.renderOrder = 2;
            _markMappingOverlay(blueMesh);
            overlayRoot.add(blueMesh);

            (spec.wheels || []).forEach(function (z) {
                [-1, 1].forEach(function (side) {
                    const pose = _tirePadCenter(spec, z, side);
                    const greenMat = new THREE.MeshBasicMaterial({
                        color: 0x43a047,
                        transparent: true,
                        opacity: 0.5,
                        depthTest: false,
                        depthWrite: false,
                        side: THREE.DoubleSide
                    });
                    VEHICLE_MAPPING_BREATH_MATERIALS.push(greenMat);
                    // X = tire thickness, Y→Z = upright tire ground length (2R).
                    const greenGeo = new THREE.PlaneGeometry(
                        pose.thickness,
                        pose.tireLength
                    );
                    const greenMesh = new THREE.Mesh(greenGeo, greenMat);
                    greenMesh.rotation.x = -Math.PI / 2;
                    greenMesh.position.set(pose.x, 0.03, pose.z);
                    greenMesh.renderOrder = 10;
                    _markMappingOverlay(greenMesh);
                    overlayRoot.add(greenMesh);
                });
            });

            group.add(overlayRoot);
        }

        // Prefer true body-paint materials; never treat glass/chrome/tires/etc as paint.
        // `bodi` covers Indonesian bus materials bodi / bodi3 (exterior shell).
        // `bache` is the French box-truck cargo tarp / outer box shell.
        const PAINT_NAME_HINT = /paint|colour|color|cabina|firstcolor|bodycolour|head_paint|base_colou?r|car_paint|carrosserie|bodi|bache/;
        // `\binter\b` is the Indonesian bus interior/seat material (not matched by
        // `interior` / `interieur`). `kaca` is Indonesian glass.
        const NON_PAINT_NAME = /glass|chrome|tire|tyre|wheel|rubber|light|lamp|mirror|interior|\binter\b|kaca|shadow|exhaust|refraction|logo|emiss|screen|speedo|accumul|hose|hub|knob|signal|windglass|plastic|bottom|matte|metal|silver|far\.|lanterna|motor|scaun|cheder|flagset|extra|perdea|door_knob|tyres|wheels|deep_black|flat_black|gloss_black|diffuse_black|blackplastic|lowparts|redlights|whiteglass|sweethome|hoses|pneu|jante|vitre|phare|chassis|interieur|volant|transmission|essuis/;

        function _isSolidPaintMaterial(mat) {
            if (!mat || !mat.color) return false;
            if (mat.map) return false;
            // normalMap alone is OK (some paints have it); skip other texture slots.
            if (mat.emissiveMap || mat.roughnessMap || mat.metalnessMap) return false;
            if (mat.aoMap || mat.lightMap || mat.bumpMap || mat.displacementMap) return false;
            return true;
        }

        function _matNameLower(mat) {
            return String((mat && mat.name) || '').toLowerCase();
        }

        function _isExcludedPaintMaterial(mat) {
            const name = _matNameLower(mat);
            if (!name) return false;
            if (NON_PAINT_NAME.test(name) && !PAINT_NAME_HINT.test(name)) return true;
            // Skip mostly-transparent glass-like materials.
            if (mat.transparent && Number(mat.opacity) < 0.92) return true;
            // glTF alphaMode=BLEND often lands as transparent with opacity=1.
            if (mat.transparent && mat.alphaMap) return true;
            return false;
        }

        function _isPreferredPaintMaterial(mat) {
            return PAINT_NAME_HINT.test(_matNameLower(mat));
        }

        function _meshLooksNonPaintByName(mesh) {
            const name = String((mesh && mesh.name) || '').toLowerCase();
            if (!name) return false;
            return /tire|tyre|wheel|rim|pneu|jante|ban|glass|vitre|kaca|window|windshield|windscreen|optic|phare|headlight|taillight|kursi|seat|inter|dasbor|dashboard/.test(name);
        }

        function _meshLocalVolume(mesh) {
            if (!mesh || !mesh.geometry) return 0;
            const geo = mesh.geometry;
            if (!geo.boundingBox) geo.computeBoundingBox();
            const bb = geo.boundingBox;
            if (!bb) return 0;
            const sx = Math.abs((bb.max.x - bb.min.x) * (mesh.scale.x || 1));
            const sy = Math.abs((bb.max.y - bb.min.y) * (mesh.scale.y || 1));
            const sz = Math.abs((bb.max.z - bb.min.z) * (mesh.scale.z || 1));
            return sx * sy * sz;
        }

        // Some trucks share one atlas material across body + wheel meshes
        // (e.g. 大型栏板货车). Recoloring that material would paint the tires
        // too. Give clearly-non-paint meshes a private material clone first so
        // only the body keeps the shared paint material.
        function isolateNonPaintMeshes(root) {
            if (!root) return;
            const byMat = {};
            root.traverse(function (mesh) {
                if (!mesh.isMesh || !mesh.material) return;
                const mats = Array.isArray(mesh.material) ? mesh.material : [mesh.material];
                mats.forEach(function (mat, idx) {
                    if (!mat) return;
                    const key = mat.uuid;
                    if (!byMat[key]) byMat[key] = [];
                    byMat[key].push({
                        mesh: mesh,
                        idx: idx,
                        multi: Array.isArray(mesh.material),
                        vol: _meshLocalVolume(mesh),
                        mat: mat
                    });
                });
            });

            Object.keys(byMat).forEach(function (key) {
                const entries = byMat[key];
                if (entries.length < 2) return;
                let maxVol = 0;
                entries.forEach(function (entry) {
                    if (entry.vol > maxVol) maxVol = entry.vol;
                });
                entries.forEach(function (entry) {
                    const byName = _meshLooksNonPaintByName(entry.mesh);
                    // Wheel meshes on the stake truck are tiny vs the cargo body.
                    const bySize = maxVol > 1e-6 && entry.vol < maxVol * 0.12;
                    if (!byName && !bySize) return;
                    const privateMat = entry.mat.clone();
                    if (entry.multi) {
                        const next = entry.mesh.material.slice();
                        next[entry.idx] = privateMat;
                        entry.mesh.material = next;
                    } else {
                        entry.mesh.material = privateMat;
                    }
                });
            });
        }

        function _meshTriangleArea(mesh, materialIndex, materialCount) {
            const geo = mesh.geometry;
            if (!geo) return 0;
            if (!geo.attributes || !geo.attributes.position) return 0;
            const pos = geo.attributes.position;
            const index = geo.index;
            const vA = new THREE.Vector3();
            const vB = new THREE.Vector3();
            const vC = new THREE.Vector3();
            let area = 0;
            function addTri(ia, ib, ic) {
                vA.fromBufferAttribute(pos, ia);
                vB.fromBufferAttribute(pos, ib);
                vC.fromBufferAttribute(pos, ic);
                area += new THREE.Triangle(vA, vB, vC).getArea();
            }
            function addRange(start, count) {
                const available = index ? index.count : pos.count;
                const end = Math.min(start + count, available);
                if (index) {
                    for (let i = start; i + 2 < end; i += 3) {
                        addTri(index.getX(i), index.getX(i + 1), index.getX(i + 2));
                    }
                } else {
                    for (let i = start; i + 2 < end; i += 3) {
                        addTri(i, i + 1, i + 2);
                    }
                }
            }

            const groups = geo.groups || [];
            const useGroups = Number(materialCount) > 1 && groups.length > 0;
            if (useGroups) {
                groups.forEach(function (group) {
                    if (Number(group.materialIndex || 0) === materialIndex) {
                        addRange(Number(group.start || 0), Number(group.count || 0));
                    }
                });
            } else {
                addRange(0, index ? index.count : pos.count);
            }

            // Malformed/no-group multi-material geometry: retain a conservative
            // fallback instead of silently treating the material as zero-area.
            if (area <= 0 && Number(materialCount) > 1) {
                addRange(0, index ? index.count : pos.count);
                if (materialCount > 0) {
                    area /= materialCount;
                }
            }
            const sx = Math.abs(mesh.scale.x) || 1;
            const sy = Math.abs(mesh.scale.y) || 1;
            const sz = Math.abs(mesh.scale.z) || 1;
            return area * sx * sy * sz;
        }

        function _paintRegionForMaterial(vehicleType, mesh, mat) {
            const splitTypes = {
                '大型罐式货车': true,
                '大型厢式货车': true,
                '牵引车及挂车': true
            };
            if (!splitTypes[vehicleType]) return 'body';

            const nodeName = String(mesh.name || '').toLowerCase();
            const matName = String((mat && mat.name) || '').toLowerCase();
            let parentName = '';
            let p = mesh.parent;
            while (p) {
                parentName += ' ' + String(p.name || '').toLowerCase();
                p = p.parent;
            }
            const blob = nodeName + ' ' + matName + ' ' + parentName;

            if (vehicleType === '大型罐式货车') {
                if (matName.indexOf('cab') >= 0) return 'body';
                if (matName.indexOf('fuel') >= 0 || matName.indexOf('tank') >= 0) return 'cargo';
                if (blob.indexOf('cab') >= 0) return 'body';
                if (blob.indexOf('fuel') >= 0 || blob.indexOf('tank') >= 0) return 'cargo';
                return 'other';
            }
            if (vehicleType === '大型厢式货车') {
                // Current French-named GLB: Carrosserie* = cab, Bache = box tarp.
                if (matName.indexOf('carrosserie') >= 0) return 'body';
                if (matName.indexOf('bache') >= 0) return 'cargo';
                // Legacy Spanish/Italian GLB used cabina for the cab paint.
                if (matName.indexOf('cabina') >= 0) return 'body';
                if (blob.indexOf('cabina') >= 0 && !matName) return 'body';
                // French truck: ignore chassis / glass / interior / fittings.
                if (
                    matName.indexOf('chassis') >= 0
                    || matName.indexOf('vitre') >= 0
                    || matName.indexOf('pneu') >= 0
                    || matName.indexOf('jante') >= 0
                    || matName.indexOf('interieur') >= 0
                    || matName.indexOf('accessoire') >= 0
                    || matName.indexOf('autre') >= 0
                    || matName.indexOf('phare') >= 0
                    || matName.indexOf('volant') >= 0
                    || matName.indexOf('tableau') >= 0
                    || matName.indexOf('transmission') >= 0
                    || matName.indexOf('essuis') >= 0
                    || matName.indexOf('sige') >= 0
                    || matName.indexOf('siege') >= 0
                ) {
                    return 'other';
                }
                // Legacy box truck: remaining named materials belong to the box.
                if (matName) return 'cargo';
                if (blob.indexOf('cabina') >= 0) return 'body';
                return 'cargo';
            }
            if (vehicleType === '牵引车及挂车') {
                if (matName.indexOf('head_paint') >= 0) return 'body';
                if (matName.indexOf('bodycolour') >= 0) return 'cargo';
                if (blob.indexOf('head_paint') >= 0) return 'body';
                if (blob.indexOf('bodycolour') >= 0) return 'cargo';
                return 'other';
            }
            return 'body';
        }

        function _parseCssColor(hex) {
            if (!hex || typeof hex !== 'string') return null;
            const c = new THREE.Color();
            try {
                c.set(hex);
                return c;
            } catch (e) {
                return null;
            }
        }

        // Tint the best body-paint material in a region.
        // Previous logic picked the largest solid material by raw triangle area, which
        // often hit undercarriage / tires instead of Car_Paint — colors were exported
        // correctly but looked unchanged in the scene.
        function applyVehiclePaint(root, config) {
            if (!root || !config) return;
            const bodyColor = _parseCssColor(config.color || config.bodyColor || null);
            const cargoColor = _parseCssColor(config.cargoColor || null);
            if (!bodyColor && !cargoColor) return;

            // Detach wheel/glass meshes that share a body atlas material.
            isolateNonPaintMeshes(root);

            const vehicleType = config.type || '';
            const regions = { body: {}, cargo: {} };

            root.traverse(function (mesh) {
                if (!mesh.isMesh || !mesh.material) return;
                const mats = Array.isArray(mesh.material) ? mesh.material : [mesh.material];
                mats.forEach(function (mat, materialIndex) {
                    if (!mat || !mat.color) return;
                    // Split vehicles often use one mesh with several material
                    // groups. Classify every material independently instead of
                    // assigning the whole mesh from its first material.
                    const region = _paintRegionForMaterial(vehicleType, mesh, mat);
                    if (region === 'other') return;
                    if (_isExcludedPaintMaterial(mat)) return;
                    const area = _meshTriangleArea(mesh, materialIndex, mats.length);
                    const key = mat.uuid;
                    if (!regions[region][key]) {
                        regions[region][key] = {
                            mat: mat,
                            area: 0,
                            solid: _isSolidPaintMaterial(mat),
                            preferred: _isPreferredPaintMaterial(mat)
                        };
                    }
                    regions[region][key].area += area;
                });
            });

            function pickBest(bucket, preferNamedPaint) {
                const items = Object.keys(bucket).map(function (k) { return bucket[k]; });
                if (!items.length) return null;
                let pool = items;
                if (preferNamedPaint) {
                    const named = items.filter(function (it) { return it.preferred; });
                    if (named.length) pool = named;
                }
                let best = null;
                pool.forEach(function (it) {
                    if (!best || it.area > best.area) best = it;
                });
                return best;
            }

            function tintMaterial(entry, color) {
                if (!entry || !entry.mat || !entry.mat.color || !color) return;
                const mat = entry.mat;
                mat.color.copy(color);
                // Dedicated named body-paint materials: drop albedo so the flat
                // sampled color is visible. Generic atlas materials (bus /
                // stake trucks) keep their map so tires/glass baked into the
                // texture stay visually distinct under a multiply tint.
                const dropMap = !!(
                    mat.map
                    && !entry.solid
                    && entry.preferred
                );
                if (dropMap) {
                    mat.map = null;
                }
                // Authored GLB paint can multiply the selected color by dark
                // vertex colors and strong metallic reflections. Normalize only
                // the recolored paint material so near-white input remains
                // visibly near white while retaining normal PBR shading.
                if ('vertexColors' in mat) mat.vertexColors = false;
                if ('metalness' in mat) mat.metalness = 0.05;
                if ('roughness' in mat) mat.roughness = 0.58;
                if ('envMapIntensity' in mat) mat.envMapIntensity = 0.2;
                if (mat.emissive && mat.emissive.isColor) {
                    // Atlas multiply tints already carry detail from the map;
                    // keep emissive subtle so tires/glass don't glow.
                    const glow = entry.preferred ? 0.06 : 0.02;
                    mat.emissive.copy(color).multiplyScalar(glow);
                    mat.emissiveIntensity = 1;
                }
                mat.needsUpdate = true;
            }

            function tintDominant(bucket, color, preferNamedPaint) {
                if (!color) return;
                const best = pickBest(bucket, preferNamedPaint);
                if (!best) return;
                // Cab paint is often split across Carrosserie / Carrosserie_2 /
                // Carrosserie_inte. When named paint is preferred, tint every
                // preferred material so doors and body stay consistent.
                if (preferNamedPaint && best.preferred) {
                    Object.keys(bucket).forEach(function (k) {
                        if (bucket[k].preferred) tintMaterial(bucket[k], color);
                    });
                    return;
                }
                tintMaterial(best, color);
            }

            const isSplit = (
                vehicleType === '大型罐式货车'
                || vehicleType === '大型厢式货车'
                || vehicleType === '牵引车及挂车'
            );
            if (isSplit) {
                if (bodyColor) tintDominant(regions.body, bodyColor, true);
                // Cargo boxes/tanks/trailers are often a large textured material
                // with a generic name. Select by actual covered area here; giving
                // every small solid material priority can recolor an invisible
                // bracket while leaving the visible cargo body unchanged.
                // Box truck is an exception: the outer shell is the named
                // textured material `Bache`. Prefer it and drop its albedo map
                // so the sampled cargo color is visible as a flat paint.
                const preferCargoNamed = (vehicleType === '大型厢式货车');
                if (cargoColor) tintDominant(regions.cargo, cargoColor, preferCargoNamed);
            } else {
                const merged = {};
                Object.keys(regions.body).forEach(function (k) { merged[k] = regions.body[k]; });
                Object.keys(regions.cargo).forEach(function (k) {
                    if (!merged[k]) {
                        merged[k] = regions.cargo[k];
                    } else {
                        merged[k].area += regions.cargo[k].area;
                        merged[k].preferred = merged[k].preferred || regions.cargo[k].preferred;
                        merged[k].solid = merged[k].solid || regions.cargo[k].solid;
                    }
                });
                tintDominant(merged, bodyColor || cargoColor, true);
            }
        }

        function createVehicle(config) {
            const group = new THREE.Group();
            group.position.set(config.position.x, config.position.y, config.position.z);
            group.rotation.set(config.rotation.x, config.rotation.y, config.rotation.z);

            const baseSpec = VEHICLE_SPECS[config.type] || VEHICLE_SPECS['小客车'];
            if (!VEHICLE_SPECS[config.type]) {
                console.warn('Unknown vehicle type:', config.type, 'fallback to 小客车');
            }
            // Per-vehicle override from the editor's "调整尺寸" dialog. Merge into a
            // local spec so LWH and wheel markers use absolute meters together —
            // do not scale the whole group afterwards (that would warp wheel Z).
            const spec = Object.assign({}, baseSpec);
            if (config.size) {
                const sw = Number(config.size.width);
                const sh = Number(config.size.height);
                const sl = Number(config.size.length);
                if (Number.isFinite(sw) && sw > 0) spec.width = sw;
                if (Number.isFinite(sh) && sh > 0) spec.height = sh;
                if (Number.isFinite(sl) && sl > 0) spec.length = sl;
                const wr = Number(config.size.wheelRadius);
                if (Number.isFinite(wr) && wr > 0) spec.wheelRadius = wr;
                if (Array.isArray(config.size.wheels) && config.size.wheels.length) {
                    const wheels = config.size.wheels
                        .map(function (v) { return Number(v); })
                        .filter(function (v) { return Number.isFinite(v); });
                    if (wheels.length) spec.wheels = wheels;
                }
            }

            const template = VEHICLE_TEMPLATE_CACHE[config.type] || VEHICLE_TEMPLATE_CACHE['小客车'];
            if (template) {
                const modelClone = cloneVehicleModel(template);
                // Rescale against the *current* spec every time (rather than
                // trusting whatever scale the template had at first load), so
                // width/length/height edits made after the model finished
                // loading (e.g. in the preview dialog) actually take effect.
                const baseSize = template.userData && template.userData.baseSize;
                if (baseSize && spec.width && spec.height && spec.length) {
                    modelClone.scale.set(
                        spec.width / baseSize.x,
                        spec.height / baseSize.y,
                        spec.length / baseSize.z
                    );
                }
                applyVehiclePaint(modelClone, config);
                group.add(modelClone);
            } else {
                console.warn('No GLB template ready yet for vehicle type:', config.type);
            }
            addSyntheticWheelMarkers(group, spec);
            addVehicleMappingOverlays(group, spec);

            return group;
        }
""".replace("__VEHICLE_SPECS__", specs_json).replace(
        "__VEHICLE_LANE_WIDTH__", lane_width_json
    ).replace(
        "__VEHICLE_EMERGENCY_LANE_WIDTH__", emergency_lane_width_json
    ).replace(
        "__SCENE_OUTLINE_WIDTH__", outline_width_json
    ).replace(
        "__VEHICLE_GLB_DATA__", glb_data_json
    ).replace(
        "__VEHICLE_GLB_CALIBRATION__", calibration_json
    )


def inject_vehicle_model_script(html_content: str, used_types=None) -> str:
    """Inject the shared vehicle model script into an HTML template."""
    if VEHICLE_MODEL_PLACEHOLDER not in html_content:
        return html_content
    return html_content.replace(
        VEHICLE_MODEL_PLACEHOLDER, get_vehicle_model_script(used_types)
    )
