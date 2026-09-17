from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("documentos", "0007_campos_interactivos"),
    ]

    operations = [
        migrations.AddField(
            model_name="documento",
            name="descripcion",
            field=models.CharField(blank=True, default="", max_length=1000),
        ),
    ]
