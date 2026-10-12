import { useState } from "react";
import { ImageView } from "./components";

export function ImageCompare({
  images,
  identity,
}: {
  images: { label: string; src?: string | null; meta?: string }[];
  identity: string;
}) {
  const [transform, setTransform] = useState({
    identity,
    zoom: 1,
    x: 50,
    y: 50,
  });
  const view =
    transform.identity === identity
      ? transform
      : { identity, zoom: 1, x: 50, y: 50 };
  return (
    <div className="image-comparison">
      <div className="comparison-tools">
        <label>
          同步缩放{" "}
          <input
            aria-label="同步缩放"
            type="range"
            min="1"
            max="4"
            step="0.25"
            value={view.zoom}
            onChange={(e) =>
              setTransform({ ...view, zoom: Number(e.target.value) })
            }
          />
        </label>
        <span>{view.zoom.toFixed(2)}×</span>
        <button
          type="button"
          onClick={() => setTransform({ identity, zoom: 1, x: 50, y: 50 })}
        >
          重置对照
        </button>
      </div>
      <div className="image-grid">
        {images.map((image) => (
          <div
            key={image.label}
            onPointerMove={(e) => {
              if (view.zoom === 1) return;
              const bounds = e.currentTarget.getBoundingClientRect();
              setTransform({
                ...view,
                x: (100 * (e.clientX - bounds.left)) / bounds.width,
                y: (100 * (e.clientY - bounds.top)) / bounds.height,
              });
            }}
          >
            <ImageView
              {...image}
              transform={{ zoom: view.zoom, x: view.x, y: view.y }}
            />
          </div>
        ))}
      </div>
      {view.zoom > 1 && (
        <p className="muted small">
          在图像内移动指针同步查看位置；对照保留各图原始像素，不表示几何配准。
        </p>
      )}
    </div>
  );
}
