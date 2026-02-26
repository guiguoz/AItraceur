import React, { useState, useRef } from 'react';
import { Buffer } from "buffer";
import ocad2geojson from 'ocad2geojson';
import { reprojectToWgs84 } from '../services/ocadCrs';

/**
 * Composant pour uploader et parser les fichiers OCAD (.ocd)
 * Utilise la librairie ocad2geojson pour extraire les données.
 */
const OcadUploader = ({ onOcadLoaded, onLoading, onError }) => {
  const [isDragging, setIsDragging] = useState(false);
  const [fileName, setFileName] = useState('');
  const fileInputRef = useRef(null);

  const handleDragEnter = (e) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(true);
  };

  const handleDragLeave = (e) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(false);
  };

  const handleDrop = (e) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(false);
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      processFile(e.dataTransfer.files[0]);
    }
  };

  const handleFileSelect = (e) => {
    if (e.target.files && e.target.files.length > 0) {
      processFile(e.target.files[0]);
    }
  };

  const processFile = (file) => {
    if (!file.name.toLowerCase().endsWith('.ocd')) {
      if (onError) onError("Le fichier doit être au format .ocd");
      return;
    }

    setFileName(file.name);
    if (onLoading) onLoading(true);

    const reader = new FileReader();

    reader.onload = (e) => {
      // Wrap in async IIFE to allow await inside FileReader callback
      (async () => {
        try {
          const buffer = e.target.result;
          const bufferData = Buffer.from(buffer);

          // FIX 1: use bufferData.byteLength (uint8Array was undefined)
          console.log(`[OCAD] Lecture du fichier ${file.name} (${bufferData.byteLength} octets)...`);

          // FIX 2: readOcad returns a Promise — must await
          const ocadMap = await ocad2geojson.readOcad(bufferData);

          const version = ocadMap.header?.version ?? ocadMap.version;
          console.log("[OCAD] Fichier lu avec succès !");
          console.log(`[OCAD] Version: ${version}`);

          const rawGeojson = ocad2geojson.ocadToGeoJson(ocadMap);
          console.log(`[OCAD] Conversion GeoJSON : ${rawGeojson.features.length} éléments trouvés`);

          const { geojson, crsInfo } = reprojectToWgs84(rawGeojson, ocadMap.getCrs());
          console.log(`[OCAD] Projection: ${crsInfo}`);

          const symbols = ocadMap.symbols || {};

          if (onOcadLoaded) {
            onOcadLoaded({
              fileName: file.name,
              version,
              crsInfo,
              rawOcad: ocadMap,
              geojson,
              symbols,
              rawFile: file,  // Pass raw file for tile generation
            });
          }
        } catch (err) {
          console.error("Erreur lors de la lecture OCAD :", err);
          if (onError) onError(`Erreur de lecture OCAD: ${err.message}`);
        } finally {
          if (onLoading) onLoading(false);
        }
      })();
    };

    reader.onerror = () => {
      if (onError) onError("Erreur de lecture du fichier");
      if (onLoading) onLoading(false);
    };

    reader.readAsArrayBuffer(file);
  };

  return (
    <>
      <div
        className={`border-2 border-dashed rounded-lg p-6 text-center cursor-pointer transition-colors ${
          isDragging
            ? 'border-blue-400 bg-blue-900/20'
            : 'border-gray-600 hover:border-blue-500 hover:bg-gray-700/30'
        }`}
        onDragEnter={handleDragEnter}
        onDragOver={handleDragEnter}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
        onClick={() => fileInputRef.current.click()}
      >
        <svg
          className="mx-auto h-10 w-10 text-gray-500 mb-3"
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth="1.5"
            d="M9 13h6m-3-3v6m5 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"
          />
        </svg>
        <p className="text-sm text-gray-300 mb-1">
          <span className="font-semibold text-blue-400">Cliquez pour choisir</span> ou glissez-déposez
        </p>
        <p className="text-xs text-gray-500">
          Fichiers OCAD .ocd (versions 10–12)
        </p>

        {fileName && (
          <div className="mt-4 inline-flex items-center px-3 py-1 rounded-full text-xs font-medium bg-green-900/40 text-green-300 border border-green-700/50">
            <svg className="mr-1.5 h-3.5 w-3.5" fill="currentColor" viewBox="0 0 20 20">
              <path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" />
            </svg>
            {fileName}
          </div>
        )}
      </div>

      <input
        type="file"
        ref={fileInputRef}
        onChange={handleFileSelect}
        className="hidden"
        accept=".ocd"
      />
    </>
  );
};

export default OcadUploader;
