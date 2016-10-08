import base64
import datetime
import stingy


class ChocolateBoxEncoder(stingy.Stingy):
    number_of_chocolates = stingy.NumberField(max_value=50)
    gift_wrapping = stingy.BooleanField()
    color = stingy.HexField(length=6)
    chocolate_type = stingy.ChoiceField(choices=['bitter', 'milky', 'white'])
    chocolate_shapes = stingy.MultipleChoiceField(
        choices=['bear', 'car', 'beer bottle', 'heart'])
    production_date = stingy.DateField(min_year=2000, max_year=2016)

chocolate_box_encoder = ChocolateBoxEncoder()

box_data = {
    'number_of_chocolates': 25,
    'gift_wrapping': True,
    'color': 'ff0000',
    'chocolate_type': 'bitter',
    'chocolate_shapes': {'bear', 'heart'},
    'production_date': datetime.date(2015, 9, 16),
}

encoded_data = chocolate_box_encoder.encode(data=box_data)
decoded_data = chocolate_box_encoder.decode(encoded_data)

print(base64.b64encode(encoded_data))
print(decoded_data)
print(decoded_data == box_data)
