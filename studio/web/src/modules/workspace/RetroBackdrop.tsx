import { Canvas, useFrame } from "@react-three/fiber";
import { Grid, Float } from "@react-three/drei";
import { useRef } from "react";
import type { Mesh } from "three";

function NeonCore() {
  const meshRef = useRef<Mesh>(null);

  useFrame((state) => {
    if (!meshRef.current) return;
    meshRef.current.rotation.y = state.clock.elapsedTime * 0.35;
    meshRef.current.rotation.x = Math.sin(state.clock.elapsedTime * 0.4) * 0.2;
  });

  return (
    <Float speed={1.8} rotationIntensity={0.35} floatIntensity={0.7}>
      <mesh ref={meshRef} position={[0, 1.1, -0.5]}>
        <octahedronGeometry args={[0.65, 0]} />
        <meshStandardMaterial color="#38bdf8" emissive="#0ea5e9" emissiveIntensity={0.5} roughness={0.1} />
      </mesh>
    </Float>
  );
}

export function RetroBackdrop() {
  return (
    <Canvas camera={{ position: [0, 2.4, 7], fov: 46 }}>
      <color attach="background" args={["#04070e"]} />
      <fog attach="fog" args={["#04070e", 6, 15]} />
      <ambientLight intensity={0.35} />
      <pointLight position={[0, 4, 2]} intensity={2.2} color="#22d3ee" />
      <pointLight position={[4, 1, 2]} intensity={1.1} color="#f59e0b" />

      <Grid
        position={[0, -1.6, 0]}
        args={[22, 18]}
        cellSize={0.7}
        cellThickness={0.5}
        cellColor="#0ea5e9"
        sectionSize={3.5}
        sectionThickness={1.4}
        sectionColor="#f97316"
        fadeDistance={22}
        fadeStrength={1}
        infiniteGrid
      />

      <NeonCore />
    </Canvas>
  );
}

