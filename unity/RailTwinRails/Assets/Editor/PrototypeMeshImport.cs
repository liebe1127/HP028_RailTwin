using UnityEditor;

public class PrototypeMeshImport : AssetPostprocessor
{
    void OnPreprocessModel()
    {
        if (assetPath.IndexOf("SecondPrototype") < 0)
        {
            return;
        }

        var importer = (ModelImporter)assetImporter;
        importer.isReadable = true;
        importer.preserveHierarchy = true;
        importer.materialImportMode = ModelImporterMaterialImportMode.ImportViaMaterialDescription;
    }
}
