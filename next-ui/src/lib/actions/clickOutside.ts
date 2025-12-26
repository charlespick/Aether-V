export function clickOutside(node: HTMLElement, callback: () => void) {
    const handleClick = (event: MouseEvent) => {
        if (node && !node.contains(event.target as Node) && !event.defaultPrevented) {
            callback();
        }
    };

    const handleTouchStart = (event: TouchEvent) => {
        if (node && !node.contains(event.target as Node) && !event.defaultPrevented) {
            callback();
        }
    };

    // Use capture phase to handle clicks before they bubble
    document.addEventListener('mousedown', handleClick, true);
    document.addEventListener('touchstart', handleTouchStart, true);

    return {
        destroy() {
            document.removeEventListener('mousedown', handleClick, true);
            document.removeEventListener('touchstart', handleTouchStart, true);
        }
    };
}
