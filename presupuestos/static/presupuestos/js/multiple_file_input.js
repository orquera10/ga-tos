// Script para manejar múltiples archivos
$(document).ready(function() {
    // Manejar la selección de archivos
    $('input[type="file"][name="archivos"]').on('change', function(e) {
        const files = e.target.files;
        const fileList = Array.from(files);
        
        // Mostrar los archivos seleccionados
        const selectedFilesContainer = $('<div class="mt-2 selected-files"></div>');
        fileList.forEach(file => {
            const fileDiv = $(`
                <div class="alert alert-info mb-1">
                    <span>${file.name} (${(file.size / 1024).toFixed(1)} KB)</span>
                    <button type="button" class="btn-close float-end remove-file" data-file="${file.name}"></button>
                </div>
            `);
            selectedFilesContainer.append(fileDiv);
        });
        
        // Insertar los archivos seleccionados debajo del input
        $(this).closest('.mb-3').append(selectedFilesContainer);
        
        // Manejar la eliminación de archivos seleccionados
        $('.remove-file').on('click', function() {
            const fileName = $(this).data('file');
            const fileInput = $(this).closest('.mb-3').find('input[type="file"][name="archivos"]')[0];
            
            // Eliminar el archivo del input
            Array.from(fileInput.files).forEach((file, index) => {
                if (file.name === fileName) {
                    const dt = new DataTransfer();
                    Array.from(fileInput.files).forEach(f => {
                        if (f.name !== fileName) {
                            dt.items.add(f);
                        }
                    });
                    fileInput.files = dt.files;
                }
            });
            
            // Eliminar el elemento visual
            $(this).closest('.alert').remove();
        });
    });
});
