"""Shared Three.js marker model script for generated scene and preview."""

import json

from core.vehicle_model_settings import load_vehicle_model_settings

MARKER_MODEL_PLACEHOLDER = "<!-- MARKER_MODEL_SCRIPT -->"


def get_marker_model_script() -> str:
    """Return the inline Three.js marker model script."""
    settings = load_vehicle_model_settings()
    marker_specs_json = json.dumps(settings.get("markerSpecs", {}), ensure_ascii=False)
    outline_width_json = json.dumps(settings["outlineWidth"], ensure_ascii=False)
    return r"""
        // 4. Dynamic markers. Keep marker rendering isolated from vehicle modeling.
        var MARKER_SPECS = __MARKER_SPECS__;
        var MARKER_OUTLINE_WIDTH = (typeof SCENE_OUTLINE_WIDTH === 'number')
            ? SCENE_OUTLINE_WIDTH
            : __MARKER_OUTLINE_WIDTH__;
        if (typeof SCENE_OUTLINE_WIDTH !== 'number') {
            SCENE_OUTLINE_WIDTH = MARKER_OUTLINE_WIDTH;
        }

        function markerMaterial(color, options = {}) {
            return new THREE.MeshStandardMaterial(
                Object.assign(
                    { color: color, roughness: 0.46, metalness: 0.08 },
                    options
                )
            );
        }

        const MARKER_EDGE_MATERIAL = new THREE.MeshBasicMaterial({
            color: 0x000000,
            transparent: false,
            opacity: 1,
            depthTest: true
        });

        function addMarkerEdgeOutline(mesh, thresholdAngle = 24) {
            if (!mesh || !mesh.geometry) return;
            if (typeof createSceneEdgeOutline === 'function') {
                const edge = createSceneEdgeOutline(mesh, thresholdAngle, MARKER_EDGE_MATERIAL);
                if (edge) mesh.add(edge);
            }
        }

        function addMarkerCylinder(group, radiusTop, radiusBottom, height, pos, mat, segments = 32) {
            const geo = new THREE.CylinderGeometry(radiusTop, radiusBottom, height, segments);
            const mesh = new THREE.Mesh(geo, mat);
            mesh.position.set(pos.x, pos.y, pos.z);
            mesh.castShadow = true;
            mesh.receiveShadow = true;
            addMarkerEdgeOutline(mesh, 24);
            group.add(mesh);
            return mesh;
        }

        function addMarkerSphere(group, radius, pos, mat, scale = { x: 1, y: 1, z: 1 }) {
            const geo = new THREE.SphereGeometry(radius, 24, 16);
            const mesh = new THREE.Mesh(geo, mat);
            mesh.position.set(pos.x, pos.y, pos.z);
            mesh.scale.set(scale.x, scale.y, scale.z);
            mesh.castShadow = true;
            mesh.receiveShadow = true;
            addMarkerEdgeOutline(mesh, 24);
            group.add(mesh);
            return mesh;
        }

        function buildTrafficConeMarker(group, spec) {
            const redMat = markerMaterial(0xd71920, { roughness: 0.58 });
            const whiteMat = markerMaterial(0xf4f4f4, { roughness: 0.42 });
            const blackMat = markerMaterial(0x262626, { roughness: 0.75 });
            const baseRadius = Math.max(spec.width, spec.length) / 2;
            addMarkerCylinder(group, baseRadius * 0.92, baseRadius, 0.08, { x: 0, y: 0.04, z: 0 }, blackMat, 36);
            addMarkerCylinder(group, baseRadius * 0.12, baseRadius * 0.72, spec.height, { x: 0, y: spec.height / 2, z: 0 }, redMat, 36);
            [
                { y: spec.height * 0.36, h: spec.height * 0.08 },
                { y: spec.height * 0.58, h: spec.height * 0.07 }
            ].forEach(function (band) {
                const centerRatio = band.y / spec.height;
                const r = baseRadius * (0.72 + (0.12 - 0.72) * centerRatio);
                addMarkerCylinder(group, r * 0.96, r * 1.04, band.h, { x: 0, y: band.y, z: 0 }, whiteMat, 36);
            });
        }

        function buildAdultMarker(group, spec) {
            const blueMat = markerMaterial(0x0b2f6b, { roughness: 0.62 });
            const darkBlueMat = markerMaterial(0x08224d, { roughness: 0.72 });
            const headRadius = Math.min(spec.width, spec.length) * 0.28;
            const headCenterY = Math.max(headRadius, spec.height - headRadius);
            const shoulderY = headCenterY - headRadius;
            const baseHeight = Math.max(spec.height * 0.10, 0.08);
            const neckHeight = Math.max(spec.height * 0.055, 0.04);
            const bodyTopY = Math.max(baseHeight + neckHeight, shoulderY - neckHeight);
            const bodyHeight = Math.max(bodyTopY - baseHeight, spec.height * 0.28);
            addMarkerCylinder(group, spec.width * 0.18, spec.width * 0.27, baseHeight, { x: 0, y: baseHeight / 2, z: 0 }, darkBlueMat, 24);
            addMarkerCylinder(group, spec.width * 0.22, spec.width * 0.32, bodyHeight, { x: 0, y: baseHeight + bodyHeight / 2, z: 0 }, blueMat, 28);
            addMarkerCylinder(group, spec.width * 0.12, spec.width * 0.14, neckHeight, { x: 0, y: bodyTopY + neckHeight / 2, z: 0 }, blueMat, 20);
            addMarkerSphere(group, headRadius, { x: 0, y: headCenterY, z: 0 }, blueMat, { x: 1, y: 1.08, z: 1 });
            [-1, 1].forEach(function (side) {
                const arm = addMarkerCylinder(group, spec.width * 0.055, spec.width * 0.055, spec.height * 0.36, { x: side * spec.width * 0.32, y: baseHeight + bodyHeight * 0.58, z: 0 }, blueMat, 16);
                arm.rotation.z = side * 0.18;
            });
        }

        function buildGuideSignMarker(group, spec) {
            const redMat = markerMaterial(0xd71920, { roughness: 0.42 });
            const yellowMat = markerMaterial(0xffd21f, { roughness: 0.38 });
            const diskRadius = spec.width / 2;
            const poleHeight = Math.max(spec.height - diskRadius * 2, spec.height * 0.45);
            const poleRadius = Math.max(0.025, spec.length * 0.18);
            addMarkerCylinder(group, poleRadius, poleRadius, poleHeight, { x: 0, y: poleHeight / 2, z: 0 }, redMat, 20);
            addMarkerCylinder(group, spec.width * 0.3, spec.width * 0.36, 0.08, { x: 0, y: 0.04, z: 0 }, redMat, 24);
            const diskY = Math.min(spec.height - diskRadius, poleHeight + diskRadius);
            const outer = addMarkerCylinder(group, diskRadius, diskRadius, spec.length, { x: 0, y: diskY, z: 0 }, redMat, 48);
            outer.rotation.x = Math.PI / 2;
            const inner = addMarkerCylinder(group, diskRadius * 0.72, diskRadius * 0.72, spec.length + 0.012, { x: 0, y: diskY, z: 0.006 }, yellowMat, 48);
            inner.rotation.x = Math.PI / 2;
        }

        // Scattered debris: a flat ground disc plus red rings that emit from the
        // centre on a fixed interval and expand outward while fading. The disc and
        // ring expansion both span up to spec.radius. A small ring pool is reused;
        // updateMarkerAnimations() (called every frame) drives the animation.
        const MARKER_DEBRIS_RING_GEOMETRY = new THREE.RingGeometry(0.82, 1.0, 48);
        const MARKER_DEBRIS_RING_DURATION = 1.6;

        function buildScatteredDebrisMarker(group, spec) {
            const radius = Math.max(0.05, spec.radius || 1.0);
            const interval = Math.max(0.05, spec.emissionInterval || 0.5);
            // Ground disc (semi-transparent red), lying flat just above the ground.
            const discMat = new THREE.MeshBasicMaterial({
                color: 0xd71920,
                transparent: true,
                opacity: 0.32,
                depthWrite: false,
                side: THREE.DoubleSide
            });
            const disc = new THREE.Mesh(new THREE.CircleGeometry(radius, 48), discMat);
            disc.rotation.x = -Math.PI / 2;
            disc.position.y = 0.02;
            disc.renderOrder = 4;
            disc.castShadow = false;
            disc.receiveShadow = false;
            group.add(disc);
            // Reusable ring pool sized to cover the rings alive at once.
            const poolSize = Math.max(3, Math.ceil(MARKER_DEBRIS_RING_DURATION / interval) + 1);
            const rings = [];
            for (let i = 0; i < poolSize; i++) {
                const ringMat = new THREE.MeshBasicMaterial({
                    color: 0xd71920,
                    transparent: true,
                    opacity: 0.0,
                    depthWrite: false,
                    side: THREE.DoubleSide
                });
                const ring = new THREE.Mesh(MARKER_DEBRIS_RING_GEOMETRY, ringMat);
                ring.rotation.x = -Math.PI / 2;
                ring.position.y = 0.04;
                ring.renderOrder = 5;
                ring.visible = false;
                ring.castShadow = false;
                ring.receiveShadow = false;
                ring.scale.set(0.001, 0.001, 1);
                group.add(ring);
                rings.push({ mesh: ring, born: -1 });
            }
            group.userData.debris = {
                radius: radius,
                interval: interval,
                duration: MARKER_DEBRIS_RING_DURATION,
                startOpacity: 0.6,
                lastEmit: -1,
                rings: rings
            };
            group.userData.hideDuringMotion = true;
        }

        // Impact point: floating yellow spheres that emit upward/outward from the
        // marker centre, similar cadence to debris but as a 3D spherical pulse.
        const MARKER_IMPACT_SPHERE_DURATION = 1.6;

        function buildImpactSphereMarker(group, spec) {
            const radius = Math.max(0.05, spec.radius || 1.5);
            const height = Math.max(0.05, spec.height || 1.5);
            const interval = Math.max(0.05, spec.emissionInterval || 1.0);
            const centerY = height * 0.5;
            const coreMat = new THREE.MeshBasicMaterial({
                color: 0xffd400,
                transparent: true,
                opacity: 0.55,
                depthWrite: false
            });
            const core = new THREE.Mesh(new THREE.SphereGeometry(Math.min(0.35, radius * 0.22), 24, 16), coreMat);
            core.position.y = centerY;
            core.renderOrder = 6;
            core.castShadow = false;
            core.receiveShadow = false;
            group.add(core);
            const poolSize = Math.max(3, Math.ceil(MARKER_IMPACT_SPHERE_DURATION / interval) + 1);
            const spheres = [];
            for (let i = 0; i < poolSize; i++) {
                const mat = new THREE.MeshBasicMaterial({
                    color: 0xffd400,
                    transparent: true,
                    opacity: 0.0,
                    depthWrite: false
                });
                const mesh = new THREE.Mesh(new THREE.SphereGeometry(1, 24, 16), mat);
                mesh.position.y = centerY;
                mesh.renderOrder = 7;
                mesh.visible = false;
                mesh.castShadow = false;
                mesh.receiveShadow = false;
                mesh.scale.set(0.001, 0.001, 0.001);
                group.add(mesh);
                spheres.push({ mesh: mesh, born: -1 });
            }
            group.userData.impact = {
                radius: radius,
                height: height,
                centerY: centerY,
                interval: interval,
                duration: MARKER_IMPACT_SPHERE_DURATION,
                startOpacity: 0.7,
                lastEmit: -1,
                spheres: spheres
            };
            group.userData.hideDuringMotion = true;
        }

        // Called once per frame from the scene animation loop. Emits a new ring on
        // each interval and grows/fades active rings. Safe to call when no debris
        // markers exist.
        function updateMarkerAnimations(scene, nowMs) {
            if (!scene) return;
            const now = nowMs / 1000;
            scene.traverse(function (obj) {
                const ds = obj.userData && obj.userData.debris;
                if (ds) {
                    if (ds.lastEmit < 0 || now - ds.lastEmit >= ds.interval) {
                        for (let i = 0; i < ds.rings.length; i++) {
                            if (ds.rings[i].born < 0) {
                                ds.rings[i].born = now;
                                ds.rings[i].mesh.visible = true;
                                break;
                            }
                        }
                        ds.lastEmit = now;
                    }
                    for (let i = 0; i < ds.rings.length; i++) {
                        const r = ds.rings[i];
                        if (r.born < 0) continue;
                        const t = (now - r.born) / ds.duration;
                        if (t >= 1) {
                            r.born = -1;
                            r.mesh.visible = false;
                            r.mesh.material.opacity = 0.0;
                            continue;
                        }
                        const s = Math.max(0.001, t * ds.radius);
                        r.mesh.scale.set(s, s, 1);
                        r.mesh.material.opacity = ds.startOpacity * (1 - t);
                    }
                }
                const impact = obj.userData && obj.userData.impact;
                if (!impact) return;
                if (impact.lastEmit < 0 || now - impact.lastEmit >= impact.interval) {
                    for (let i = 0; i < impact.spheres.length; i++) {
                        if (impact.spheres[i].born < 0) {
                            impact.spheres[i].born = now;
                            impact.spheres[i].mesh.visible = true;
                            break;
                        }
                    }
                    impact.lastEmit = now;
                }
                for (let i = 0; i < impact.spheres.length; i++) {
                    const s = impact.spheres[i];
                    if (s.born < 0) continue;
                    const t = (now - s.born) / impact.duration;
                    if (t >= 1) {
                        s.born = -1;
                        s.mesh.visible = false;
                        s.mesh.material.opacity = 0.0;
                        continue;
                    }
                    const scale = Math.max(0.001, t * impact.radius);
                    s.mesh.scale.set(scale, scale, scale);
                    s.mesh.position.y = impact.centerY + t * impact.height * 0.35;
                    s.mesh.material.opacity = impact.startOpacity * (1 - t);
                }
            });
        }

        function createSceneMarker(config) {
            const group = new THREE.Group();
            const rotation = config.rotation || { x: 0, y: 0, z: 0 };
            const position = config.position || { x: 0, y: 0, z: 0 };
            group.position.set(position.x || 0, position.y || 0, position.z || 0);
            group.rotation.set(rotation.x || 0, rotation.y || 0, rotation.z || 0);
            const spec = MARKER_SPECS[config.type] || MARKER_SPECS['安全椎桶'] || { kind: 'trafficCone', width: 0.4, length: 0.4, height: 0.8 };
            if (spec.kind === 'adult') buildAdultMarker(group, spec);
            else if (spec.kind === 'guideSign') buildGuideSignMarker(group, spec);
            else if (spec.kind === 'scatteredDebris') buildScatteredDebrisMarker(group, spec);
            else if (spec.kind === 'impactSphere') buildImpactSphereMarker(group, spec);
            else buildTrafficConeMarker(group, spec);
            return group;
        }
""".replace("__MARKER_SPECS__", marker_specs_json).replace(
        "__MARKER_OUTLINE_WIDTH__", outline_width_json
    )


def inject_marker_model_script(html_content: str) -> str:
    """Inject the shared marker model script into an HTML template."""
    if MARKER_MODEL_PLACEHOLDER not in html_content:
        return html_content
    return html_content.replace(MARKER_MODEL_PLACEHOLDER, get_marker_model_script())
