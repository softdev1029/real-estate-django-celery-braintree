var sherpa = window.sherpa = {};
sherpa._templates = {};
function render(id, data) {
    if (!sherpa._templates[id]) {
        sherpa._templates[id] = _.template($('#' + id).html());
    }
    return sherpa._templates[id](data);
}