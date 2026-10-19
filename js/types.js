// V11.8.0: Centralized Type Definitions
// Этот файл не выполняется в рантайме, он нужен только для JSDoc / TS.

/**
 * @typedef {Object} Keypoint
 * @property {string} name
 * @property {number} x
 * @property {number} y
 * @property {number} visibility
 */

/**
 * @typedef {Object} BoxData
 * @property {number} x
 * @property {number} y
 * @property {number} w
 * @property {number} h
 * @property {string} label
 * @property {number|null} confidence
 * @property {boolean} frozen
 * @property {string|null} behavior
 * @property {number|null} animal_id
 * @property {Keypoint[]} keypoints
 */

/**
 * @typedef {Object} ImageData
 * @property {number} id
 * @property {string} filename
 * @property {number} width
 * @property {number} height
 * @property {number} annotation_count
 * @property {number|null} min_confidence
 * @property {number|null} avg_confidence
 * @property {number} low_conf_count
 * @property {number[]} tag_ids
 * @property {number|null} video_id
 * @property {number|null} frame_index
 * @property {string|null} created_at
 * @property {number|null} file_size
 * @property {number|null} timestamp_sec
 * @property {string[]} behaviors
 */

/**
 * @typedef {Object} AppState
 * @property {BoxData[]} boxes
 * @property {number} selectedIndex
 * @property {Set<number>} multiSelected
 * @property {number|null} currentImageId
 * @property {number} zoom
 * @property {number} panX
 * @property {number} panY
 */

export {};
