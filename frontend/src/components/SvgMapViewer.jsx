import { useRef, useEffect, useState, useMemo } from 'react';
import { TransformWrapper, TransformComponent } from 'react-zoom-pan-pinch';

const IOF_COLOR = '#9b2cae';

export function SvgMapViewer({ mapData, courseControls = [], activeTool = 'view', onMapClick }) {
    const containerRef = useRef(null);
    const [svgContent, setSvgContent] = useState('');
    const [viewBox, setViewBox] = useState({ x: 0, y: 0, w: 0, h: 0 });

    useEffect(() => {
        if (mapData?.svg) {
            setSvgContent(mapData.svg);
            // Extract viewBox from SVG string
            const match = mapData.svg.match(/viewBox="([^"]+)"/);
            if (match) {
                const [x, y, w, h] = match[1].split(' ').map(Number);
                setViewBox({ x, y, w, h });
            }
        }
    }, [mapData]);

    // Coordinate mapping: WGS84 -> SVG Pixel
    // The backend provides geoBounds (WGS84) and ocadBounds (Native/Pixel units at resolution)
    const project = (lat, lng) => {
        if (!mapData?.geoBounds || !viewBox.w) return { x: 0, y: 0 };
        const { minLng, maxLng, minLat, maxLat } = mapData.geoBounds;

        // Percent across the geo bounds
        const pctX = (lng - minLng) / (maxLng - minLng);
        const pctY = (maxLat - lat) / (maxLat - minLat); // Lat is inverted vs SVG Y

        return {
            x: viewBox.x + pctX * viewBox.w,
            y: viewBox.y + pctY * viewBox.h
        };
    };

    // Inverse mapping: SVG Pixel -> WGS84
    const unproject = (x, y) => {
        if (!mapData?.geoBounds || !viewBox.w) return { lat: 0, lng: 0 };
        const { minLng, maxLng, minLat, maxLat } = mapData.geoBounds;

        const pctX = (x - viewBox.x) / viewBox.w;
        const pctY = (y - viewBox.y) / viewBox.h;

        return {
            lng: minLng + pctX * (maxLng - minLng),
            lat: maxLat - pctY * (maxLat - minLat)
        };
    };

    const handleClick = (e) => {
        if (activeTool === 'view' || !onMapClick) return;

        const rect = e.currentTarget.getBoundingClientRect();
        // This is tricky with zoom/pan. We need the coordinates relative to the SVG inside the zoom wrapper.
        // However, react-zoom-pan-pinch handles the transform. 
        // We'll use the event's native coordinates if possible or pass the raw click.
    };

    const orderedControls = useMemo(() => {
        return [...courseControls]
            .filter(c => ['start', 'control', 'finish'].includes(c.type))
            .sort((a, b) => a.order - b.order)
            .map(c => ({ ...c, ...project(c.lat, c.lng) }));
    }, [courseControls, mapData, viewBox]);

    if (!mapData) return null;

    return (
        <div className="w-full h-full bg-gray-950 overflow-hidden relative">
            <TransformWrapper
                initialScale={1}
                minScale={0.1}
                maxScale={20}
                centerOnInit={true}
                disabled={activeTool !== 'view'}
            >
                {({ zoomIn, zoomOut, resetTransform, ...rest }) => (
                    <>
                        <div className="absolute top-4 right-4 z-50 flex flex-col gap-2">
                            <button onClick={() => zoomIn()} className="p-2 bg-gray-800 rounded border border-gray-700 hover:bg-gray-700">➕</button>
                            <button onClick={() => zoomOut()} className="p-2 bg-gray-800 rounded border border-gray-700 hover:bg-gray-700">➖</button>
                            <button onClick={() => resetTransform()} className="p-2 bg-gray-800 rounded border border-gray-700 hover:bg-gray-700">🏠</button>
                        </div>

                        <TransformComponent wrapperClass="!w-full !h-full">
                            <div
                                className="relative cursor-crosshair"
                                onClick={(e) => {
                                    // Calculate coordinates in SVG space
                                    const svg = e.currentTarget.querySelector('svg');
                                    if (!svg) return;
                                    const pt = svg.createSVGPoint();
                                    pt.x = e.clientX;
                                    pt.y = e.clientY;
                                    const svgPt = pt.matrixTransform(svg.getScreenCTM().inverse());
                                    const latlng = unproject(svgPt.x, svgPt.y);
                                    onMapClick(latlng);
                                }}
                            >
                                {/* The Map SVG */}
                                <div
                                    dangerouslySetInnerHTML={{ __html: svgContent }}
                                    className="pointer-events-none select-none"
                                />

                                {/* Course Overlay */}
                                <svg
                                    className="absolute inset-0 pointer-events-none"
                                    viewBox={`${viewBox.x} ${viewBox.y} ${viewBox.w} ${viewBox.h}`}
                                    xmlns="http://www.w3.org/2000/svg"
                                >
                                    {/* Polyline */}
                                    {orderedControls.length >= 2 && (
                                        <polyline
                                            points={orderedControls.map(c => `${c.x},${c.y}`).join(' ')}
                                            fill="none"
                                            stroke={IOF_COLOR}
                                            stroke-width={viewBox.w / 500}
                                            stroke-linejoin="round"
                                        />
                                    )}

                                    {/* Controls */}
                                    {orderedControls.map((c, i) => (
                                        <g key={c.id}>
                                            {c.type === 'start' ? (
                                                <polygon
                                                    points={`${c.x},${c.y - 10} ${c.x + 10},${c.y + 10} ${c.x - 10},${c.y + 10}`}
                                                    fill="none"
                                                    stroke={IOF_COLOR}
                                                    stroke-width="2"
                                                />
                                            ) : c.type === 'finish' ? (
                                                <g>
                                                    <circle cx={c.x} cy={c.y} r="8" fill="none" stroke={IOF_COLOR} stroke-width="2" />
                                                    <circle cx={c.x} cy={c.y} r="12" fill="none" stroke={IOF_COLOR} stroke-width="2" />
                                                </g>
                                            ) : (
                                                <g>
                                                    <circle cx={c.x} cy={c.y} r="10" fill="none" stroke={IOF_COLOR} stroke-width="2" />
                                                    <text
                                                        x={c.x + 12} y={c.y + 12}
                                                        fill={IOF_COLOR}
                                                        fontSize="10"
                                                        fontWeight="bold"
                                                        style={{ paintOrder: 'stroke', stroke: 'white', strokeWidth: 0.5 }}
                                                    >
                                                        {c.order - 1}
                                                    </text>
                                                </g>
                                            )}
                                        </g>
                                    ))}
                                </svg>
                            </div>
                        </TransformComponent>
                    </>
                )}
            </TransformWrapper>
        </div>
    );
}
