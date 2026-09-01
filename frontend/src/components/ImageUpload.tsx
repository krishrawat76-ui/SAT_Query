"use client";

import { useCallback } from "react";
import { useDropzone } from "react-dropzone";
import { UploadCloud, X, FileImage } from "lucide-react";
import type { UploadedImage, Modality } from "@/types/api";

const ACCEPTED = {
    "image/png": [".png"],
    "image/jpeg": [".jpg", ".jpeg"],
    "image/tiff": [".tif", ".tiff"],
};

function formatBytes(bytes: number): string {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function isPreviewable(file: File): boolean {
    return file.type === "image/png" || file.type === "image/jpeg";
}

interface ImageUploadProps {
    images: UploadedImage[];
    onChange: (images: UploadedImage[]) => void;
    maxImages?: number;
    onRequestClose?: () => void;
}

/**
 * Popover dropzone panel — rendered above the prompt bar when the "+"
 * attach button is toggled open. For the compact preview strip shown
 * once images exist (rendered directly above the prompt bar even while
 * this panel is closed), see `AttachmentChips` below.
 */
export default function ImageUpload({
    images,
    onChange,
    maxImages = 2,
    onRequestClose,
}: ImageUploadProps) {
    const onDrop = useCallback(
        (accepted: File[]) => {
            const room = maxImages - images.length;
            if (room <= 0) return;

            const next: UploadedImage[] = accepted.slice(0, room).map((file) => ({
                id: `${file.name}-${file.size}-${Date.now()}-${Math.random()
                    .toString(36)
                    .slice(2, 8)}`,
                file,
                preview: isPreviewable(file) ? URL.createObjectURL(file) : "",
                modality: "optical",
            }));

            onChange([...images, ...next]);
        },
        [images, onChange, maxImages]
    );

    const { getRootProps, getInputProps, isDragActive } = useDropzone({
        onDrop,
        accept: ACCEPTED,
        disabled: images.length >= maxImages,
        multiple: maxImages > 1,
    });

    const removeImage = (id: string) => {
        const target = images.find((img) => img.id === id);
        if (target?.preview) URL.revokeObjectURL(target.preview);
        onChange(images.filter((img) => img.id !== id));
    };

    const updateModality = (id: string, modality: Modality) => {
        onChange(
            images.map((img) => (img.id === id ? { ...img, modality } : img))
        );
    };

    const atCapacity = images.length >= maxImages;

    return (
        <div className="w-[340px] rounded-3xl border border-slate-200/80 bg-white p-4 shadow-xl">
            <div className="mb-3 flex items-center justify-between">
                <h2 className="text-sm font-medium text-slate-900">Satellite imagery</h2>
                <div className="flex items-center gap-2">
                    <span className="text-xs text-slate-400">
                        {images.length}/{maxImages}
                    </span>
                    {onRequestClose && (
                        <button
                            type="button"
                            onClick={onRequestClose}
                            className="flex h-6 w-6 items-center justify-center rounded-full text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-700"
                            aria-label="Close"
                        >
                            <X className="h-3.5 w-3.5" />
                        </button>
                    )}
                </div>
            </div>

            {!atCapacity && (
                <div
                    {...getRootProps()}
                    className={`flex cursor-pointer flex-col items-center justify-center gap-2 rounded-2xl border-2 border-dashed px-4 py-8 text-center transition-colors ${isDragActive
                            ? "border-slate-400 bg-slate-50"
                            : "border-slate-200 bg-slate-50/50 hover:border-slate-300 hover:bg-slate-50"
                        }`}
                >
                    <input {...getInputProps()} />
                    <UploadCloud className="h-5 w-5 text-slate-400" strokeWidth={1.5} />
                    <p className="text-xs text-slate-600">
                        {isDragActive ? "Drop to upload" : "Drag images here, or click to browse"}
                    </p>
                    <p className="text-[11px] text-slate-400">
                        PNG, JPEG, GeoTIFF · up to {maxImages} images
                    </p>
                </div>
            )}

            {images.length > 0 && (
                <div className={`grid gap-2.5 ${!atCapacity ? "mt-3" : ""} grid-cols-2`}>
                    {images.map((img) => (
                        <div
                            key={img.id}
                            className="overflow-hidden rounded-2xl border border-slate-200/80 bg-white"
                        >
                            <div className="relative aspect-video bg-slate-100">
                                {img.preview ? (
                                    // eslint-disable-next-line @next/next/no-img-element
                                    <img
                                        src={img.preview}
                                        alt={img.file.name}
                                        className="h-full w-full object-cover"
                                    />
                                ) : (
                                    <div className="flex h-full w-full flex-col items-center justify-center gap-1 text-slate-400">
                                        <FileImage className="h-5 w-5" strokeWidth={1.5} />
                                        <span className="text-[10px]">No preview</span>
                                    </div>
                                )}
                                <button
                                    type="button"
                                    onClick={() => removeImage(img.id)}
                                    className="absolute right-1.5 top-1.5 flex h-6 w-6 items-center justify-center rounded-full bg-white/90 text-slate-600 shadow-sm backdrop-blur-md transition-colors hover:bg-white hover:text-slate-900"
                                    aria-label={`Remove ${img.file.name}`}
                                >
                                    <X className="h-3 w-3" />
                                </button>
                            </div>

                            <div className="space-y-1.5 p-2">
                                <p
                                    className="truncate text-[11px] font-medium text-slate-700"
                                    title={img.file.name}
                                >
                                    {img.file.name}
                                </p>
                                <div className="flex items-center justify-between gap-1.5">
                                    <span className="text-[10px] text-slate-400">
                                        {formatBytes(img.file.size)}
                                    </span>
                                    <select
                                        value={img.modality}
                                        onChange={(e) =>
                                            updateModality(img.id, e.target.value as Modality)
                                        }
                                        className="rounded-full border border-slate-200 bg-slate-50 px-2 py-0.5 text-[10px] font-medium text-slate-600 outline-none transition-colors focus:border-slate-400"
                                    >
                                        <option value="optical">Optical</option>
                                        <option value="sar">SAR</option>
                                    </select>
                                </div>
                            </div>
                        </div>
                    ))}
                </div>
            )}
        </div>
    );
}

interface AttachmentChipsProps {
    images: UploadedImage[];
    onRemove: (id: string) => void;
    onModalityChange: (id: string, modality: Modality) => void;
}

/**
 * Compact preview strip shown directly above the prompt bar once images
 * are attached, so the full dropzone panel can stay closed.
 */
export function AttachmentChips({
    images,
    onRemove,
    onModalityChange,
}: AttachmentChipsProps) {
    if (images.length === 0) return null;

    return (
        <div className="mb-2 flex flex-wrap gap-2">
            {images.map((img) => (
                <div
                    key={img.id}
                    className="flex items-center gap-2 rounded-2xl border border-slate-200/80 bg-white py-1.5 pl-1.5 pr-2 shadow-sm"
                >
                    <div className="flex h-8 w-8 items-center justify-center overflow-hidden rounded-xl bg-slate-100">
                        {img.preview ? (
                            // eslint-disable-next-line @next/next/no-img-element
                            <img
                                src={img.preview}
                                alt={img.file.name}
                                className="h-full w-full object-cover"
                            />
                        ) : (
                            <FileImage className="h-4 w-4 text-slate-400" strokeWidth={1.5} />
                        )}
                    </div>
                    <span
                        className="max-w-[110px] truncate text-xs text-slate-600"
                        title={img.file.name}
                    >
                        {img.file.name}
                    </span>
                    <select
                        value={img.modality}
                        onChange={(e) => onModalityChange(img.id, e.target.value as Modality)}
                        className="rounded-full border border-slate-200 bg-slate-50 px-1.5 py-0.5 text-[10px] font-medium text-slate-600 outline-none"
                    >
                        <option value="optical">OPTICAL</option>
                        <option value="sar">SAR</option>
                    </select>
                    <button
                        type="button"
                        onClick={() => onRemove(img.id)}
                        className="flex h-5 w-5 items-center justify-center rounded-full text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-700"
                        aria-label={`Remove ${img.file.name}`}
                    >
                        <X className="h-3 w-3" />
                    </button>
                </div>
            ))}
        </div>
    );
}