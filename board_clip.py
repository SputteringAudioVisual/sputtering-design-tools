"""Board contour clipping, without moving or rescaling the artwork."""
import math


def outline_contours(layer):
    edges = []
    for d in layer.drawables:
        if d['type'] == 'line' and d.get('polarity', 'dark') == 'dark':
            a, b = (d['x1'], d['y1']), (d['x2'], d['y2'])
            if math.dist(a, b) > 1e-7:
                edges.append((a, b))
    key = lambda p: (round(p[0], 4), round(p[1], 4))
    adjacency = {}
    for i, (a, b) in enumerate(edges):
        adjacency.setdefault(key(a), []).append(i)
        adjacency.setdefault(key(b), []).append(i)
    if not edges or any(len(ids) != 2 for ids in adjacency.values()):
        raise ValueError('El contorno PCB debe estar cerrado para recortar la imagen.')
    remaining = set(range(len(edges)))
    contours = []
    while remaining:
        index = min(remaining)
        start, end = edges[index]
        path = [start, end]
        remaining.remove(index)
        while key(end) != key(start):
            candidates = [i for i in adjacency[key(end)] if i in remaining]
            if len(candidates) != 1:
                raise ValueError('No se puede reconstruir el contorno PCB cerrado.')
            index = candidates[0]
            a, b = edges[index]
            end = b if key(a) == key(end) else a
            path.append(end)
            remaining.remove(index)
        area2 = sum(a[0]*b[1]-b[0]*a[1] for a,b in zip(path,path[1:]))
        if len(path) < 4 or abs(area2) < 1e-9:
            raise ValueError('Contorno PCB sin superficie.')
        contours.append(path)
    return contours


def clip_mask(mask, contours, x, y, width, height):
    """Clip an image mask in world coordinates; nested contours are cutouts."""
    from PIL import Image, ImageDraw, ImageChops
    board = Image.new('L', mask.size, 0)
    for contour in contours:
        part = Image.new('L', mask.size, 0)
        points = [((px-x)*mask.width/width, (y+height-py)*mask.height/height)
                  for px, py in contour]
        ImageDraw.Draw(part).polygon(points, fill=255)
        board = ImageChops.difference(board, part)
    return ImageChops.multiply(mask, board)


def outside_regions(contours, bounds):
    """Decompose the outside into simple trapezoids (no compound Gerber regions)."""
    xmin, ymin, xmax, ymax = bounds
    ys = sorted({ymin, ymax, *(y for path in contours for _, y in path if ymin < y < ymax)})
    edges = [(a, b) for path in contours for a, b in zip(path, path[1:]) if a[1] != b[1]]
    for low, high in zip(ys, ys[1:]):
        mid = (low+high)/2
        active = [(a, b) for a, b in edges if min(a[1], b[1]) < mid < max(a[1], b[1])]
        def at(edge, y):
            a, b = edge
            return a[0]+(b[0]-a[0])*(y-a[1])/(b[1]-a[1])
        active.sort(key=lambda edge: at(edge, mid))
        if len(active) % 2:
            raise ValueError('Contorno PCB ambiguo: no se puede calcular el recorte.')
        pairs = [(None, active[0])] if active else [(None, None)]
        pairs += [(active[i], active[i+1]) for i in range(1, len(active)-1, 2)]
        if active:
            pairs.append((active[-1], None))
        for left, right in pairs:
            l0, l1 = (at(left, low), at(left, high)) if left else (xmin, xmin)
            r0, r1 = (at(right, low), at(right, high)) if right else (xmax, xmax)
            if r0-l0 > 1e-8 or r1-l1 > 1e-8:
                yield [(l0, low), (r0, low), (r1, high), (l1, high), (l0, low)]


def clipping_commands(contours, bounds, layer):
    div = 25.4 if layer.unit == 'IN' else 1.0
    def point(p, op):
        x = round(p[0]/div*10**layer.format_x[1])
        y = round(p[1]/div*10**layer.format_y[1])
        return f'X{x}Y{y}D0{op}*'
    commands = ['G01*', '%LPC*%']
    for path in outside_regions(contours, bounds):
        commands += ['G36*', point(path[0], 2)]
        commands.extend(point(p, 1) for p in path[1:])
        commands.append('G37*')
    return commands+['%LPD*%', 'G01*']
